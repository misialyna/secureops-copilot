# Notatki z sesji odbiorczej — Etap 7

Środowisko: `uvicorn` (prod, bez `--reload`), frontend zbudowany (`npm run build`), Postgres lokalny
(docker-compose), `.env` przełączony na lokalny `DATABASE_URL` na czas sesji.

Zasada tej sesji: znalezione problemy są tu tylko **notowane**, bez zmian w kodzie w trakcie.

## Zgłoszone problemy

<!-- kolejne wpisy w formacie:

### [nr] Krótki tytuł

- **Co zaobserwowano**:
- **Kroki do odtworzenia**:
- **Oczekiwane zachowanie**:
- **Wstępna diagnoza**:
- **Status**: do naprawy / do dalszej analizy / nie jest błędem

-->

### 1. Brak treści błędu 429 od Groq w logach uvicorna

- **Co zaobserwowano**: `POST /incidents/{thread_id}/resume` zwrócił 429 (widoczne w logu dostępu
  uvicorna: `"POST ... HTTP/1.1" 429 Too Many Requests`), ale bez treści wyjątku — nasz
  `groq_error_handler` (backend/app/main.py) łapie `GroqError` i zwraca czysty JSON z `detail`,
  ale nic nie loguje po drodze (ani pełnego komunikatu Groqa, ani nagłówków rate-limit typu
  `x-ratelimit-remaining-tokens`).
- **Kroki do odtworzenia**: dowolne wywołanie grafu (start/resume), które trafi w limit Groqa.
- **Oczekiwane zachowanie (do dyskusji)**: gdyby handler logował `exc.message`/`exc.body` (i
  ewentualnie nagłówki `x-ratelimit-*` z odpowiedzi Groqa) na poziomie WARNING/ERROR przed
  zwróceniem czystego JSON-a do klienta, dałoby to możliwość zdiagnozowania *post factum*, który
  dokładnie limit (TPM czy TPD) i przy jakim zużyciu został przekroczony.
- **Wstępna diagnoza**: próbowałam odtworzyć błąd minimalnym bezpośrednim wywołaniem do Groq
  (ten sam klucz, `chat.completions.create` z `max_tokens=1`) już po zdarzeniu — limit zdążył się
  zresetować (limity darmowego tieru Groqa są zwykle liczone per minutę), więc wywołanie się
  powiodło i nie odzyskałam konkretnych liczb (limit/used/requested) z tego zdarzenia.
- **Status**: do dalszej analizy — jeśli 429 pojawi się ponownie w trakcie tej sesji, zgłoś od
  razu, zanim minie ~1 minuta, to spróbuję złapać treść na żywo tym samym sposobem.
- **Aktualizacja**: patrz ZNALEZISKO #3 poniżej — dokładnie ten problem, zgłoszony żywo w trakcie
  odbioru z konkretnym kontekstem (przejściowy 429 w środku tury `resume`).

### 2. ZNALEZISKO #1 (priorytet: wysoki) — przejściowy 429 w środku `resume` trwale "zabija" wątek

- **Co zaobserwowano** (zgłoszone przez użytkowniczkę, na żywo, podczas odbioru): przejściowy
  429 od Groq w trakcie tury `/resume` powoduje, że wątek trwale przechodzi w `status: "failed"`
  — bez żadnej możliwości wznowienia. Sesja (klasyfikacja, plan, audit_log zebrane do tego
  momentu) zostaje zachowana i widoczna, ale dalszy postęp jest niemożliwy inaczej niż przez
  założenie zupełnie nowego zgłoszenia od zera.
- **Dlaczego to priorytet wysoki**: 429 jest z definicji *przejściowy* (limit się resetuje w
  ciągu sekund/minut) — a mimo to skutek dla użytkownika jest identyczny jak trwały błąd danych
  czy logiki. To marnuje całą dotychczasową pracę grafu (klasyfikację, retrieve, tools, plan,
  a w gorszym przypadku też zatwierdzoną i wykonaną akcję active z `audit_log`) z powodu czegoś,
  co często wystarczyłoby po prostu ponowić.
- **Decyzja produktowa użytkowniczki**: mechanizm wznowienia wątku ze stanu `"failed"` **przestaje
  być traktowany jako opcjonalny "nice to have"** zaplanowany "kiedyś przy observability" — staje
  się **obowiązkową pozycją** planu etapu observability/Langfuse, a nie propozycją do rozważenia.
- **Status**: do naprawy — zaplanowane do etapu observability (nie w tej sesji, zgodnie z zasadą
  "brak zmian w kodzie w trakcie odbioru").

### 3. ZNALEZISKO #2 — handler `GroqError` powinien logować treść wyjątku + nagłówki `x-ratelimit-*`

- **Co zaobserwowano**: podczas dzisiejszej diagnozy (patrz wpis 1 powyżej) nie dało się ustalić,
  który limit Groqa (TPM czy TPD) został przekroczony ani jakie było zużycie w momencie 429,
  ponieważ `groq_error_handler` (backend/app/main.py) nie loguje nic — ani `exc.message`/`exc.body`,
  ani nagłówków odpowiedzi Groqa (`x-ratelimit-remaining-tokens`, `x-ratelimit-limit-tokens` itp.).
  Diagnozowanie musiało odbyć się "na ślepo", przez osobne, spóźnione wywołanie testowe do Groq
  (limit zdążył się już zresetować, więc nie odzyskano konkretnych liczb z tego zdarzenia).
- **Oczekiwane zachowanie**: handler powinien zalogować (WARNING/ERROR) pełną treść wyjątku i
  dostępne nagłówki `x-ratelimit-*` **przed** zwróceniem czystego JSON-a do klienta — klient
  nadal dostaje ten sam przyjazny komunikat, ale w logach serwera zostaje ślad pozwalający
  ustalić po fakcie, który limit i przy jakim zużyciu został przekroczony.
- **Status**: do naprawy — zaplanowane do etapu observability, razem ze znaleziskiem #1 (ten
  sam obszar: widoczność i odzyskiwalność po błędach Groqa).

### 4. ZNALEZISKO #3 (UX, priorytet: średni) — brak drogi powrotu do nowego zgłoszenia z poziomu UI

- **Co zaobserwowano**: po wejściu w sesję istniejącego wątku (a zwłaszcza w stanie `failed`)
  użytkownik jest "uwięziony" w tym widoku — jedyny sposób powrotu do ekranu nowego zgłoszenia
  to ręczna edycja adresu URL (usunięcie `?thread=...`), czego nikt sam z siebie nie odgadnie.
  Szczególnie dotkliwe w połączeniu ze znaleziskiem #1: `FailedView` instruuje "załóż nowe
  zgłoszenie", ale nie daje żadnej klamki, żeby to zrobić.
- **Kroki do odtworzenia**: otwórz dowolny wątek przez `?thread=...` (dowolny status), spróbuj
  wrócić do ekranu nowego zgłoszenia bez ręcznej edycji paska adresu.
- **Oczekiwane zachowanie / do poprawki**:
  1. Przycisk "Nowe zgłoszenie" w nagłówku aplikacji (widoczny zawsze) — czyści `?thread=` z URL
     i resetuje stan sesji (`threadId`, `incident`, `evidenceFiles` z powrotem do wartości
     początkowych).
  2. Ten sam przycisk/akcja wprost w `FailedView` — skoro jego tekst każe "założyć nowe
     zgłoszenie", powinien dawać do tego bezpośrednią możliwość, a nie tylko instrukcję słowną.
- **Status**: do naprawy — dotyczy `App.tsx` (nagłówek) i `FailedView.tsx`; nie w tej sesji,
  zgodnie z zasadą "brak zmian w kodzie w trakcie odbioru".

### 5. ZNALEZISKO #4 — diagnoza 429: dzienny limit TPD wyczerpany (hipoteza A potwierdzona), nie minutowy TPM (B odrzucona)

**Metoda**: (1) minimalne wywołanie `chat.completions.create(max_tokens=1)` — przeszło bez błędu,
brak 429 w danym momencie. (2) natychmiast drugie wywołanie z dużym promptem (~9000 tokenów,
lorem ipsum, 36 000 znaków) — **od razu zwróciło 429**. Pełna treść błędu i nagłówki poniżej.

**Pełna treść błędu Groq (RateLimitError, status 429):**

```
Rate limit reached for model `llama-3.3-70b-versatile` in organization `org_01k99kbtbzev2vz949etyk6m1s`
service tier `on_demand` on tokens per day (TPD): Limit 100000, Used 99809, Requested 6510.
Please try again in 1h30m59.616s. Need more tokens? Upgrade to Dev Tier today at
https://console.groq.com/settings/billing
```

**Nagłówki odpowiedzi (istotne):**

```
retry-after: 5460
x-ratelimit-limit-requests: 1000
x-ratelimit-limit-tokens: 12000          <- to jest limit TPM (per minutę), NIE ten, który padł
x-ratelimit-remaining-requests: 997
x-ratelimit-remaining-tokens: 12000      <- PEŁNY zapas minutowy — TPM nie jest wąskim gardłem
x-ratelimit-reset-requests: 4m19.2s
x-ratelimit-reset-tokens: 1ms
```

**Rozstrzygnięcie: HIPOTEZA A potwierdzona (dzienna pula TPD na wyczerpaniu), HIPOTEZA B odrzucona.**

Dowód rozstrzygający: nagłówki pokazują `x-ratelimit-remaining-tokens: 12000` — czyli limit
**minutowy (TPM 12 000) jest w pełni dostępny**, zero zużycia w bieżącej minucie. Mimo to duże
wywołanie i tak dostało 429, a treść błędu explicite mówi `tokens per day (TPD): Limit 100000,
Used 99809` — **99.8% dziennego budżetu tokenów już wykorzystane** w chwili testu. Minimalne
wywołanie (1 token żądany) zmieściło się w pozostałym zapasie (100000 − 99809 = 191 tokenów), ale
duże (6510 żądanych) już nie.

**Ważne zastrzeżenie**: to wyczerpanie TPD to najpewniej efekt **kumulacji całodziennego ruchu**
na tym samym kluczu/organizacji — dzisiejsze intensywne testy E2E (curl, zrzuty ekranu, wielokrotne
`start`/`resume`, w tym retry na `tool_use_failed` w `plan`) plus sama sesja odbiorcza — a nie
koszt jednej, pojedynczej tury `resume`. Limit dzienny na tym tierze (100 000 tokenów) jest niski
i dzieli się między WSZYSTKIE wywołania z całego dnia na tym kluczu, nie tylko produkcyjny ruch.

**Szacunek kosztu tokenowego jednej tury `resume` (classify re-run + tools + plan), rząd wielkości:**

Zmierzone bezpośrednio z kodu (`backend/app/graph/nodes.py`) i z realnego stanu wątku
`c9420c81-4c89-4d19-a69f-8cff8255f424` z dzisiejszej sesji (odczytane z Postgresa przez
`GET /incidents/{id}` — pole `sources` zawiera prawdziwy tekst 5 pobranych fragmentów RAG):

| Składnik | Rozmiar | Szacunek tokenów |
| --- | --- | --- |
| `CLASSIFY_SYSTEM_PROMPT` (EN, zmierzone) | 1149 znaków | ~287 tok |
| `TOOLS_SYSTEM_PROMPT` (EN, zmierzone) | 1070 znaków | ~268 tok |
| `PLAN_SYSTEM_PROMPT` (EN, zmierzone) | 3490 znaków | ~872 tok |
| `sources` (5 fragmentów RAG, **realne dane** z wątku dzisiejszej sesji, EN) | 3695 znaków | ~924 tok |
| `incident_description` (×3, raz na węzeł — **szacunek**, treść niedostępna przez API, PL) | ~90–750 znaków/węzeł | ~30–250 tok/węzeł |
| `clarifications` (classify+plan, ×2 — **szacunek**, niedostępne przez API, PL) | ~250 znaków | ~80 tok |
| nazwy plików dowodowych (`tools`, tylko nazwy, nie treść) | ~10 znaków | ~3 tok |
| `tool_results` sformatowane (jeśli `tools` zdążył się wykonać — **szacunek**) | ~200–400 znaków | ~50–100 tok |

**Suma wejściowa (input) jednej pełnej tury**: rząd wielkości **~2 800–3 500 tokenów**,
zdominowany przez `PLAN_SYSTEM_PROMPT` (872 tok) + realne fragmenty RAG (924 tok) — te dwa
składniki to ~65% całości i są w dużej mierze stałe niezależnie od długości zgłoszenia.

**Zastrzeżenie do tego szacunku**: `incident_description` i odpowiedzi na pytania doprecyzowujące
nie są nigdzie zwracane przez API (nie ma ich w `IncidentResponse`), więc nie da się ich odczytać
retrospektywnie z Postgresa przez istniejące endpointy — oszacowane na podstawie tekstów, które
faktycznie podałam do wklejenia w tej sesji. Węzeł `tools` może też wywołać LLM **do 5 razy**
w jednej turze (`bind_tools`, pętla — patrz `README.md`/`MAX_TOOL_CALLS` w `nodes.py`), z rosnącym
kontekstem przy każdym kolejnym wywołaniu — jeśli faktycznie doszło do >1 wywołania, realny koszt
tej tury mógł być **wyraźnie wyższy** niż powyższy szacunek dla pojedynczego wywołania `tools`.

Rząd wielkości: przy ~3–5K tokenów na turę, dzienny budżet 100 000 tokenów starcza na **ok.
20–30 pełnych tur `resume`** — niedużo, jeśli dzień obejmuje też intensywne testowanie deweloperskie
na tym samym kluczu.

- **Status**: informacyjne (diagnoza zakończona, hipoteza A potwierdzona liczbami). Sama poprawka
  (np. przejście na wyższy tier, throttling po stronie appki, cache'owanie RAG) — do decyzji poza
  tą sesją, zgodnie z zasadą "brak zmian w kodzie w trakcie odbioru".

### 6. ZNALEZISKO #5 (jakość raportu — przekłamania) — Executive summary sprzeczne ze stanem faktycznym

- **Co zaobserwowano** (przegląd redakcyjny raportu z przebiegu 1): sekcja "Executive summary"
  zawiera dwa twierdzenia sprzeczne z rzeczywistym przebiegiem sprawy:
  1. Raport stwierdza, że "aktywność jest już nieaktywna", podczas gdy odpowiedź użytkowniczki na
     pytanie doprecyzowujące brzmiała dosłownie "nie wiemy" (niepewność co do tego, czy atak
     wciąż trwa).
  2. Raport stwierdza, że "zostały podjęte działania w celu zablokowania [adresu IP]", podczas
     gdy zaproponowana akcja `block_ip` została **odrzucona** przez analityka — sekcja "Podjęte
     działania" tego samego raportu opisuje to poprawnie (odrzucono), więc "Executive summary"
     **przeczy własnemu raportowi** kawałek niżej.
- **Dlaczego to poważne**: model systematycznie zamienia niepewność/negację w stanowczą, fałszywą
  pewność. W raporcie bezpieczeństwa, który ma być podstawą decyzji, to nie jest kosmetyczny
  błąd stylu — to błąd merytoryczny mogący prowadzić do złych decyzji (np. uznanie sprawy za
  zamkniętą, gdy zagrożenie może nadal trwać).
- **Status**: do adresowania w etapie ewaluacji (jakość/wierność generowanego tekstu względem
  stanu grafu — kandydat na twardą metrykę, nie tylko przegląd ręczny). Nie w tej sesji.

### 7. ZNALEZISKO #6 (zniekształcenie findings) — parafraza zmienia sens ustaleń narzędzia

- **Co zaobserwowano**: raport opisuje ustalenie `log_analyzer` jako "zmiany w plikach i
  katalogach", podczas gdy narzędzie faktycznie zaraportowało **zmiany kont i uprawnień**
  (utworzenie nowego użytkownika `eve` + dodanie go do grupy `sudo`). To nie jest to samo — plik/
  katalog vs. konto/uprawnienie to różne kategorie ryzyka w analizie incydentu.
- **Dlaczego to poważne**: parafraza LLM-a nie tylko upraszcza, ale **zmienia znaczenie
  merytoryczne** konkretnego, weryfikowalnego ustalenia narzędzia read-only — dokładnie tego typu
  danych, które raport ma cytować wiernie.
- **Status**: do adresowania w etapie ewaluacji, razem ze ZNALEZISKIEM #5 (ten sam obszar:
  wierność raportu względem stanu źródłowego). Nie w tej sesji.

### 8. ZNALEZISKO #7 (cytowania) — citation recall = 0 na żywym Groq **w raporcie końcowym** (zawężone)

- **Co zaobserwowano**: w raporcie z przebiegu 1 nie pojawił się ani jeden marker `[n]`, ani
  sekcja "## References" — mimo że mechanizm whitelisty cytowań (`app/graph/report.py`) był już
  przetestowany jednostkowo i w testach z fake LLM. Na żywym Groq model po prostu nie zacytował
  niczego **w tekście raportu końcowego**.
- **Doprecyzowanie zakresu (po przeglądzie `screenshot-report.png`, przebieg 2)**: "zero cytowań"
  dotyczy **wyłącznie** mechanizmu `[n]`/References w węźle `report.py` (raport końcowy).
  Cytowania w planie diagnostyki (`DiagnosticStep.citations`, renderowane przez frontend jako
  `[1]`/`[2]` w panelu "Plan diagnostyki") **działają poprawnie** i były widoczne na żywo w
  przebiegu 2 — potwierdzone bezpośrednim obejrzeniem `screenshot-report.png` (Priorytet 3 → `[1]`,
  Priorytet 6 → `[2]`). To dwa niezależne mechanizmy: numeracja cytowań planu żyje wyłącznie po
  stronie frontendu (`DiagnosticPlanView`, liczona z `plan.steps[].citations`), a whitelist/strip
  w `report.py` buduje swoją własną listę `[n]` osobno, z `retrieved_chunks` + cytowań planu —
  ale to `report_llm` musi faktycznie *użyć* markerów z tej listy w generowanym tekście, i na
  żywym Groq tego nie robi.
- **Dlaczego to ważne**: to nie jest awaria mechanizmu (whitelist + strip w `report.py` działają
  poprawnie — po prostu nie miały czego przyciąć, bo `report_llm` nie wygenerował żadnych
  markerów), tylko sygnał, że **prompt tego konkretnego węzła nie skłania modelu do cytowania
  wystarczająco skutecznie** w praktyce — mimo że dokładnie te same dane (cytowania planu,
  potwierdzone jako trafne) są już dostępne w stanie grafu i **inny węzeł/frontend z nich
  poprawnie korzysta**.
- **Dobry trop do zbadania jako pierwszy krok w ewaluacji**: `report_llm` mógłby dostać explicite
  listę "`plan.steps[].citations` już potwierdzone jako prawdziwe" jako osobną, wyeksponowaną
  część promptu (zamiast polegać wyłącznie na ogólnej whiteliście zbudowanej z
  `retrieved_chunks`) — skoro te cytowania już przeszły przez plan i wiadomo, że są zasadne,
  report node nie musi ich "odkrywać na nowo" z surowych fragmentów RAG.
- **Status**: metryka priorytetowa do etapu ewaluacji — "citation recall" **w raporcie końcowym**
  (jaki odsetek wygenerowanych raportów faktycznie zawiera cytowania tam, gdzie plan miał
  przypisane `[source_id, page]`) powinien wejść do zestawu metryk jako pierwszej klasy obywatel,
  z powyższym tropem jako pierwszą hipotezą do przetestowania. Nie w tej sesji.

### 9. ZNALEZISKO #8 (spójność językowa) — plan/caveats/uzasadnienia po angielsku mimo polskiego zgłoszenia

- **Co zaobserwowano**: `plan.steps` (description/rationale/expected_evidence), `plan.caveats`
  oraz `justification`/`risk_note` propozycji akcji wyszły po angielsku, mimo że zgłoszenie było
  po polsku. Sam finalny raport (`report` node) poprawnie wyszedł po polsku.
- **Wstępna diagnoza**: instrukcja "pisz w tym samym języku co zgłoszenie" jest obecna w
  `PLAN_SYSTEM_PROMPT` i `APPROVAL_SYSTEM_PROMPT` (`backend/app/graph/nodes.py`), więc to nie jest
  brak instrukcji — model po prostu nie zawsze się do niej stosuje na żywym Groq, zwłaszcza przy
  polach, które nie są głównym trzonem odpowiedzi (uzasadnienia, zastrzeżenia). Report node
  najwyraźniej ma silniejsze/skuteczniejsze wymuszenie języka niż plan/approval.
- **Status**: do adresowania w etapie ewaluacji (test spójności językowej między węzłami jako
  osobna metryka/asercja). Nie w tej sesji.

### 10. ZNALEZISKO #9 (padding planu) — kroki 5-7 to ogólniki wypełniające widełki

- **Co zaobserwowano**: w planie z 7 kroków, kroki 1-4 są konkretne i osadzone w realiach
  sprawy, kroki 5-7 są ogólnikowe ("monitoruj system", "przejrzyj plan IR") — sprawiają wrażenie
  wypełniaczy dodanych, żeby dobić do górnej granicy widełek.
- **Wstępna diagnoza**: `PLAN_SYSTEM_PROMPT` prosi o "4 do 7 kroków" — sztywne widełki z dolną
  granicą 4 mogą zachęcać model do generowania planu do pełna, nawet gdy sprawa uzasadnia mniej
  konkretnych kroków.
- **Do rozważenia** (nie decyzja, tylko propozycja do oceny w ewaluacji): zmiana instrukcji na
  coś w rodzaju "tyle kroków, ile faktycznie wynika z ustaleń, maksymalnie 7" — bez sztywnego
  minimum.
- **Status**: do adresowania w etapie ewaluacji. Nie w tej sesji.

### 11. ZNALEZISKO #10 — stepper pomija "Pytania" po przejściu dalej — **przyczyna potwierdzona w kodzie**, nie "niestabilny próg"

- **Kontekst**: w przebiegu 1 zaobserwowano, że stepper w prawej kolumnie nie pokazywał etapu
  "Pytania" jako ukończonego, mimo że pytania doprecyzowujące faktycznie wystąpiły. Wstępna
  hipoteza mówiła o "niestabilnym progu kompletności zgłoszenia między przebiegami" —
  **zweryfikowana i odrzucona poniżej.**
- **Weryfikacja**: sprawdzone bezpośrednio w Postgresie (`checkpoint_writes` dla wątku z
  przebiegu 1, `docker exec docker-postgres-1 psql ...`). Historia zapisów jednoznacznie
  potwierdza: `classify` → `branch:to:clarify` → `clarify` zapisuje `__interrupt__`, po
  wznowieniu zapisuje `clarifications` → `branch:to:classify` (pętla powrotna) → drugi `classify`
  → `branch:to:retrieve` → `retrieve` → `tools` (tu dopiero błąd, patrz ZNALEZISKO #1/#4).
  **Pytania doprecyzowujące na pewno wystąpiły i zostały poprawnie obsłużone przez graf.**
  Hipoteza o "niestabilnym progu" jest więc błędna — problem nie leży po stronie grafu/backendu.
- **Rzeczywista przyczyna (potwierdzona w kodzie)**: `frontend/src/state/stages.ts`,
  funkcja `deriveStages()` — etap `'questions'` jest dodawany do zbioru `active` tylko gdy
  `status === 'awaiting_clarification'`, ale **nigdy nie jest dodawany do zbioru `done`** w
  żadnej z gałęzi obsługujących późniejsze statusy (`awaiting_approval`, `completed`, `failed`).
  Efekt: gdy wątek przechodzi dalej po odpowiedzi na pytania, etap "Pytania" wraca do pustego
  kółka ("pending") zamiast pozostać odhaczony — mimo że faktycznie się wydarzył i zakończył
  sukcesem. To dokładnie to, co zaobserwowano w przebiegu 1 (status `failed` po awarii w `tools`,
  więc gałąź `failed` w `deriveStages` — ta gałąź w ogóle nie dotyka `'questions'`).
- **Poprawka do rozważenia** (nie teraz): w gałęziach `awaiting_approval`/`completed`/`failed`
  dodać `done.add('questions')`, gdy `incident.classification` istnieje i wiadomo, że pytania
  były (np. na podstawie obecności czegoś w odpowiedzi wskazującego na przebytą klaryfikację —
  do zaprojektowania, bo `IncidentResponse` obecnie nie zwraca `clarifications` wprost).
- **Status**: do naprawy — drobna, dobrze zlokalizowana poprawka w `stages.ts`; nie w tej sesji.

### 12. ZNALEZISKO #11 (priorytet: wysoki — kontrakt `propose_actions`) — propozycja akcji bez realnej podstawy merytorycznej

- **Co zaobserwowano**: w przebiegu 2 (ransomware, `docs/report-sample-2.md`) model zaproponował
  `block_ip({"ip": "nie dotyczy"})` — w scenariuszu, w którym nie było żadnego konkretnego adresu
  IP do zablokowania. `APPROVAL_SYSTEM_PROMPT` (`backend/app/graph/nodes.py`) explicite dopuszcza
  brak propozycji jako poprawną, bezpieczną odpowiedź ("it is always safe, and often correct, to
  propose nothing"), a mimo to model wolał wygenerować propozycję-placeholder niż nic nie
  proponować.
- **Dlaczego to poważne**: walidacja formatu w `firewall.py` (`ip_address(ip)` rzuca `ValueError`
  dla `"nie dotyczy"`) odrzuciła tę propozycję — ale **przypadkowo, jako efekt uboczny**
  parsowania adresu IP, nie jako celowa siatka bezpieczeństwa sprawdzająca *sensowność*
  propozycji. To dwie różne warstwy: (a) "czy to jest syntaktycznie poprawny adres IP" —
  zadziałała; (b) "czy ta propozycja ma w ogóle merytoryczne uzasadnienie w ustaleniach/opisie
  incydentu" — **nie istnieje jako osobna kontrola**. Przy innym scenariuszu model mógłby równie
  łatwo podstawić **syntaktycznie poprawny, ale merytorycznie zmyślony** adres IP (np. wzięty "z
  powietrza" zamiast z realnych findings) — wtedy żadna istniejąca walidacja by tego nie złapała,
  a propozycja trafiłaby do panelu zgód wyglądając na w pełni uzasadnioną. Analityk zatwierdzający
  akcję byłby wtedy **jedyną linią obrony** przed wykonaniem działania na podstawie zmyślonych
  danych.
- **Do zbadania w etapie ewaluacji**:
  1. Wzmocnić `APPROVAL_SYSTEM_PROMPT` jawnym przykładem: "brak realnej podstawy w findings/opisie
     = brak propozycji, nigdy propozycja-placeholder (np. IP 'nie dotyczy', 'unknown', 'N/A')".
  2. Rozważyć twardą walidację po stronie kodu (nie tylko formatu): czy proponowany adres IP
     faktycznie występuje w `tool_results`/opisie incydentu, a nie jest zmyślony przez model —
     dodatkowa siatka bezpieczeństwa niezależna od tego, czy string "wygląda jak" poprawny IP.
- **Status**: do zbadania w etapie ewaluacji — priorytet wysoki (dotyczy bezpieczeństwa samego
  mechanizmu human-in-the-loop, nie tylko jakości tekstu raportu). Nie w tej sesji.

## Obserwacje pozytywne

- **`FailedView` zachował się wzorcowo** przy ZNALEZISKU #1: uczciwy, nieklamiący stan (nie udaje
  "completed"), częściowe dane (klasyfikacja/plan/audit_log) pozostały widoczne, komunikat jasno
  tłumaczył sytuację po polsku. Dokładnie tak, jak było zaprojektowane.
- **Model jest bardziej dociekliwy, niż zakładano — korekta wcześniejszego założenia.** Przebieg 2
  (ransomware) użył celowo bardzo szczegółowego opisu zgłoszenia, przygotowanego z założeniem, że
  "kompletny opis pomija pytania doprecyzowujące". Założenie **było błędne**: `classify` i tak
  zadał 4 pytania (eksfiltracja danych przed zaszyfrowaniem, dokładny zakres/liczba zaszyfrowanych
  plików, potwierdzenie braku dalszych infekcji z innych stacji, integralność kopii zapasowej).
  To **dobra cecha jakościowa modelu, nie wada** — pytania są konkretne i merytorycznie zasadne
  (dokładnie te informacje faktycznie brakowały w opisie), nie są przypadkowym artefaktem.
  Koryguje to wcześniejsze, zbyt uproszczone założenie o progu "kompletności" zgłoszenia.
- **Ścieżka zatwierdzenia + persistence potwierdzona bezbłędnie na obu przebiegach.** Zamknięcie
  karty w stanie `awaiting_approval` i powrót przez `?thread=...` w URL zadziałało poprawnie
  zarówno przy odrzuceniu (przebieg 1), jak i przy zatwierdzeniu (przebieg 2).

## Podsumowanie sesji

**Sesja odbiorcza Etapu 7: W PEŁNI ZAKOŃCZONA.** Oba przebiegi — brute force zakończony
odrzuceniem propozycji `block_ip` (`thread_id 73c01e80-480c-475c-83b2-3ae68c4a7925`,
`docs/report-sample-1.md`) i ransomware zakończony zatwierdzeniem
(`thread_id 8ad508cc-054e-43de-a90a-99de6bd857fc`, `docs/report-sample-2.md`) — przeszły przez UI
end-to-end, z testem persistence sesji (zamknięcie karty w stanie `awaiting_approval` i powrót
przez `?thread=...` w URL) potwierdzonym na obu.

Wszystkie znaleziska z tej sesji (**ZNALEZISKO #1–#11**) są skategoryzowane i zaadresowane do
etapu observability/ewaluacji — żadne z nich **nie blokuje** uznania Etapu 7 za zamknięty:

- #1 (wznowienie wątku `failed`) i #2 (logowanie treści `GroqError` + nagłówków) — **naprawione
  w tej rundzie** (`fix(ux): recover paths after failed runs and rate limits`, commit `e22c4ef`)
  poza samym wznowieniem `failed`, które pozostaje świadomie odłożone na etap observability.
- #3 (brak drogi powrotu do nowego zgłoszenia) — **naprawione w tej samej rundzie** (przycisk
  "Nowe zgłoszenie" w nagłówku + CTA w `FailedView`).
- #4 (diagnoza 429 — TPD wyczerpane) — informacyjne, zdiagnozowane liczbowo, decyzja co do
  poprawki (throttling, wyższy tier, cache RAG) odłożona.
- #5, #6, #9 (jakość/wierność raportu: przekłamania w Executive summary, zniekształcenie
  findings, padding planu) — do etapu ewaluacji, jako materiał do zaprojektowania metryk
  wierności generowanego tekstu.
- #7 (citation recall = 0 w raporcie końcowym na żywym Groq — zawężone: cytowania planu
  działają poprawnie, problem dotyczy wyłącznie `report_llm`) — do etapu ewaluacji, jako
  metryka priorytetowa, z konkretnym tropem do przetestowania jako pierwszym krokiem.
- #8 (niespójność językowa plan/caveats/justification vs. report) — do etapu ewaluacji.
- #10 (stepper gubi "Pytania" po przejściu dalej) — drobna, zlokalizowana poprawka w
  `frontend/src/state/stages.ts`, odłożona do kolejnej rundy.
- #11 (priorytet wysoki — `propose_actions` proponuje akcje bez realnej podstawy, np.
  `block_ip({"ip": "nie dotyczy"})`) — do zbadania w ewaluacji: wzmocnienie promptu +
  rozważenie twardej walidacji "czy IP pochodzi z findings, nie zmyślone".

Etap 7 (frontend — konsola analityka, pełny cykl incydentu w przeglądarce, build produkcyjny
serwowany przez FastAPI, CI zielone dla obu jobów) uznany za **zamknięty**.
