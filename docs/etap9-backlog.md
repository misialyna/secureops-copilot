# Backlog na Etap 9

## PILNE: try/except wokół `preview_tool` w `propose_actions` — priorytet 1

**Dlaczego priorytet wyższy niż walidacja semantyczna (patrz niżej):** to dotyczy stabilności
całego grafu (crash, cała inwokacja ginie), nie tylko jakości pojedynczej propozycji. Crash jest
gorszy niż zła propozycja, którą analityk może odrzucić na panelu zgód.

**Mechanizm:** `propose_actions_node` w `backend/app/graph/nodes.py` (linia ok. 402) woła
`preview_tool(draft.tool_name, draft.args)` bez żadnego zabezpieczenia. `draft.args` to zupełnie
dowolny `dict[str, Any]` pochodzący prosto ze structured output LLM-a (`ApprovalGateDecision` →
`ProposedActionDraft`) — nigdzie po drodze nie jest sprawdzane, czy zawiera wymagane przez dane
narzędzie klucze. `preview_tool` robi `spec.preview_fn(**(args or {}))`, czyli jeśli LLM nie poda
wymaganego argumentu (np. `ip` dla `block_ip`), dostajemy goły, nieobsłużony `TypeError`, który
wychodzi z węzła grafu, przez `graph.ainvoke()`, aż do FastAPI — gdzie nie ma na niego żadnego
handlera (jest tylko `@app.exception_handler(GroqError)`), więc kończy się to jako nieczytelny
500 i wątek zostaje w niejasnym stanie (bez interruptu, bez wpisu w audit_log).

**Dziś prompt engineering przypadkiem podniósł częstość tego zdarzenia z 1/15 do 4/15
scenariuszy.** Poprawka `APPROVAL_SYSTEM_PROMPT` (zasada "no basis, no proposal", Etap 8 Część D)
miała ograniczyć wymyślanie placeholderów przez model. Efekt uboczny, zmierzony bezpośrednio: w
części przypadków, gdzie model wcześniej wpisywał string-placeholder (`"nie dotyczy"`, `"unknown"`
— łapane grzecznie przez walidację formatu IP), teraz zwraca `args: {}` (pusty dict) — co trafia
prosto w ten sam nieobsłużony `TypeError`, zamiast w czysto obsłużony błąd walidacji.

**Reprodukcja — 4 scenariusze tej samej klasy błędu** (pełne dane w
[`eval/report.md`](eval/report.md), sekcja "Part D — measured fixes → Groundless action rate"):

1. `malware-keylogger` — oryginalny, wcześniej znany przypadek (Etap 8 Część A/B): crash już przy
   pierwszym pełnym przebiegu, przed jakąkolwiek poprawką promptu.
2. `data-breach-s3-bucket` — po poprawce promptu: `args: {}` (wcześniej `{"ip": "nie dotyczy"}`).
3. `data-breach-db-exfil` — po poprawce promptu: `args: {}` (wcześniej `{"ip": "unknown"}`).
4. `insider-threat-departing-employee` — po poprawce promptu: `args: {}` (wcześniej
   `{"ip": "employee_workstation_ip"}`).

Wszystkie 3 nowe przypadki (2–4) zostały potwierdzone bezpośrednim wywołaniem
`preview_tool("block_ip", {})`, które rzuca identyczny
`TypeError: block_ip() missing 1 required positional argument: 'ip'`.

**Proponowany zakres naprawy:** owinąć wywołanie `preview_tool(draft.tool_name, draft.args)` w
`propose_actions` w `try/except`, analogicznie do tego, jak `execute_tool` w węźle `tools`
(`backend/app/graph/nodes.py`, linie ok. 347–355) już łapie wyjątki i zamienia je w `ToolResult`
z ostrzeżeniem zamiast pozwalać im zabić cały graf. Odrzucona/nieudana propozycja powinna zostać
pominięta (tak jakby model nic nie zaproponował), a nie crashować `propose_actions_node`.

## Priorytet 2: walidacja semantyczna proponowanych argumentów

Nawet gdy `preview_tool` przestanie crashować, sam fakt, że argument ma poprawny format, nie
znaczy, że ma sens merytorycznie — patrz ZNALEZISKO #11, przypadek `ransomware-fileserver` /
`dos-volumetric` (Etap 8), gdzie model zaproponował syntaktycznie poprawny adres IP
(`203.0.113.5`), złapany tylko dlatego, że akurat wpadł w zarezerwowany zakres RFC 5737. Docelowo:
sprawdzać w kodzie, czy proponowany IP faktycznie występuje w `tool_results`/evidence danego
wątku, zanim propozycja trafi na panel zgód — przenosi to gwarancję z "zaufaj promptowi" na
"zweryfikuj w kodzie", tak jak już działa `execute_tool`/`PermissionError`.
