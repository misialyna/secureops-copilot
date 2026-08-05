# Etap 8 — Evaluation report

Scenarios: 15 run, 1 ended in an uncaught error. All 15 planned scenarios collected.

## Metrics

| Metric | Value | Recommendation |
| --- | --- | --- |
| Classification accuracy (exact) | 79% | known limitation |
| Classification accuracy (incl. reasonable neighbor) | 93% | informational |
| Severity in expected range | 100% | informational |
| Citation recall — final report (ZNALEZISKO #7) | 7% | Etap 9 (prompt fix candidate) |
| Citation recall — plan (contrast) | 79% | no action, already works |
| Citation precision | 100% | expected ~100%, see note below |
| Groundless action rate (ZNALEZISKO #11) | 91% | fix now (Part D) |
| Plan padding (mean fraction generic in steps 5+) | 85% | Etap 9 |
| Token cost per scenario (median / p90) | 10362 / 15584 | capacity planning |
| Full runs fitting in 100k tokens/day | 9 | capacity planning |

## Interpretation

### Classification accuracy
14 scenarios scored. Exact-category accuracy 79%, rising to 93% when a defensible neighbor category (e.g. ransomware/malware) counts as correct. Severity landed in the expected range 100% of the time. The deliberately ambiguous scenario got confidence 0.70 vs. a mean of 0.82 for unambiguous ones — confidence did drop for genuine uncertainty, as hoped.

### Citations — report vs. plan (ZNALEZISKO #7, narrowed)
The final report cited at least once in 7% of scenarios, vs. 79% for the plan panel's own citations. This gap is the actual finding: the same citation *data* (plan.steps[].citations, retrieved_chunks) is available to both, but report_llm doesn't reliably use [n] markers while the plan mechanism (rendered by the frontend, not an LLM decision) does. Citation precision measured at 100% on 4 marker(s) found — expected to be ~100% by construction (report.py's whitelist already strips anything invalid before this measurement ever sees it), so this confirms the mechanism works rather than revealing something new; the low marker COUNT is the real signal, not the precision percentage.

### Groundless action rate (ZNALEZISKO #11)
91% of the 11 no-clear-target scenarios still got a proposed action — but this is three genuinely different failure modes, not one, and blending them into a single rate would hide which ones actually matter:

- **Uncaught crash** — propose_actions raises before anything is even captured — 1:
  - `malware-keylogger` (error): `TypeError: block_ip() missing 1 required positional argument: 'ip'`
- **Placeholder string** — caught by plain IP format validation — 7:
  - `phishing-single-user` (completed): `{'ip': 'nie dotyczy'}`
  - `phishing-mass-campaign` (completed): `{'ip': 'link_domain_ip_address'}`
  - `unauthorized-access-leaked-creds` (completed): `{'ip': 'nieznany'}`
  - `data-breach-s3-bucket` (completed): `{'ip': 'nie dotyczy'}`
  - `data-breach-db-exfil` (completed): `{'ip': 'unknown'}`
  - `insider-threat-departing-employee` (completed): `{'ip': 'employee_workstation_ip'}`
  - `other-badge-cloning` (completed): `{'ip': 'nie dotyczy'}`
- **Looked like a real IP** — caught only because it happened to land in a reserved/test range, not because anything detected it was fabricated — 2:
  - `ransomware-fileserver` (completed): `{'ip': '203.0.113.5'}`
  - `dos-volumetric` (completed): `{'ip': '203.0.113.5'}`

The **looked_valid_but_reserved_range** case (2) is the one that actually matters most: it's the closest real occurrence to what ZNALEZISKO #11 originally warned about — 'model mógłby podstawić syntaktycznie poprawny, ale merytorycznie zmyślony adres IP' — a fabricated-looking IP that isn't an obvious placeholder like 'nie dotyczy'. It was only caught because it happened to fall in a reserved range (RFC 5737); a fabricated *public-looking* IP would sail straight through every existing check and reach the approval panel looking legitimate.

### Plan padding (ZNALEZISKO #9)
Across 14 plans with 5+ steps, a mean of 85% of steps from position 5 onward share no specific content word with the original incident description — i.e. they don't reference anything concrete from the case (no server name, filename, IP), unlike the earlier, concrete steps. Consistent with the acceptance-session observation.

### Faithfulness of the Executive summary (ZNALEZISKO #5)
Checked 6 of 14 eligible scenario(s) successfully (8 check(s) failed — see note below); 6 flagged at least one sentence stating something as certain that the clarification answers explicitly marked unknown. This is a list for human review, not an automatic verdict:

- **malware-worm-smb**:
  - "Zespół sieciowy nie potwierdził jeszcze, czy adres IP jest legalnym klientem czy atakującym."
- **ransomware-ssh-bruteforce**:
  - "Serwer aplikacyjny web02 padł ofiarą ataku ransomware"
  - "Zespół bezpieczeństwa znalazł w logach systemowych serię nieudanych prób logowania SSH"
  - "za dnia serwer był w pełni sprawny"
- **phishing-mass-campaign**:
  - "Zespół bezpieczeństwa otrzymał kilkanaście zgłoszeń od pracowników dotyczących tej samej wiadomości phishingowej"
  - "Na razie nie potwierdzono, czy ktokolwiek z pracowników faktycznie wprowadził swoje dane na tej stronie"
- **unauthorized-access-leaked-creds**:
  - "System monitorujący logowania do VPN firmowego oznaczył jako podejrzane logowanie na konto jednego z inżynierów z kraju, w którym firma nie ma żadnych pracowników ani klientów"
  - "Sesja z nietypowej lokalizacji trwała kilka minut i została automatycznie zakończona przez wygaśnięcie tokenu"
  - "Inżynier zaprzecza, by logował się spoza biura"
- **dos-application-layer**:
  - "Atak ten jest klasyfikowany jako odmowa usługi o wysokiej wadze i prawdopodobieństwie 0.80."
  - "Zespół operacyjny podejmuje działania w celu zidentyfikowania źródła ataku i jego powstrzymania."
- **data-breach-s3-bucket**:
  - "Niezależny badacz bezpieczeństwa poinformował firmę, że jeden z magazynów danych w chmurze zawierający kopie zapasowe bazy klientów był publicznie dostępny bez uwierzytelnienia od co najmniej trzech tygodni z powodu błędnej konfiguracji uprawnień."
  - "Nie wiadomo, czy ktokolwiek inny odkrył ten magazyn danych wcześniej."

**Note**: 8 check(s) failed deterministically (3 identical retries all failed the same way) for **phishing-single-user**, **ransomware-fileserver**, **unauthorized-access-ssh-bruteforce**, **dos-volumetric**, **data-breach-db-exfil**, **insider-threat-departing-employee**, **other-badge-cloning**, **ambiguous-encryption-no-ransom-note** — llama-3.1-8b-instant emitted its tool call as literal text instead of a parseable response for these specific inputs. A data point on 8B's structured-output reliability, relevant to the Part C discussion below.

### Part C — classify-only 8B vs 70B comparison
On 5 scenarios: 70B matched the expected category 5/5, 8B matched 5/5. 

| Scenario | Expected | 70B (conf.) | 8B (conf.) |
| --- | --- | --- | --- |
| phishing-single-user | phishing | phishing (0.80) | phishing (0.80) |
| malware-worm-smb | malware | malware (0.80) | malware (0.90) |
| ransomware-fileserver | ransomware | ransomware (0.90) | ransomware (0.90) |
| ransomware-ssh-bruteforce | ransomware | ransomware (0.90) | ransomware (0.90) |
| phishing-mass-campaign | phishing | phishing (0.80) | phishing (0.90) |

Matches the accuracy of 70B on this small sample — a candidate for moving classification to the cheaper/faster model specifically, which would help both token budget and rate-limit resilience (ZNALEZISKO #4). Sample size (5) is too small to be conclusive on its own; treat as a promising signal to expand in Etap 9, not a final answer.

## Part D — measured fixes

### Groundless action rate — propose_actions prompt fix

`APPROVAL_SYSTEM_PROMPT` was extended with an explicit "no basis, no proposal" rule and a worked
example. Measured by replaying just the `propose_actions` LLM call against each scenario's
already-stored classification/plan/tool_results (not a full graph re-run) — isolates the prompt's
effect from run-to-run variance elsewhere in the pipeline. 9 of the 10 originally-groundless
scenarios could be replayed this way (`malware-keylogger`, the crash case, has no stored
plan/classification to replay from, since the original run errored before capturing it):

| Scenario | Before | After | Outcome |
| --- | --- | --- | --- |
| phishing-single-user | `{"ip": "nie dotyczy"}` | *(no proposal)* | **fixed** |
| other-badge-cloning | `{"ip": "nie dotyczy"}` | *(no proposal)* | **fixed** |
| ransomware-fileserver | `{"ip": "203.0.113.5"}` | *(no proposal)* | **fixed** |
| dos-volumetric | `{"ip": "203.0.113.5"}` | *(no proposal)* | **fixed** |
| phishing-mass-campaign | `{"ip": "link_domain_ip_address"}` | `{"ip": "nie dotyczy"}` | not fixed — different placeholder, same severity |
| unauthorized-access-leaked-creds | `{"ip": "nieznany"}` | `{"ip": "nie dotyczy"}` | not fixed — different placeholder, same severity |
| data-breach-s3-bucket | `{"ip": "nie dotyczy"}` | `{}` | **not fixed — WORSE** |
| data-breach-db-exfil | `{"ip": "unknown"}` | `{}` | **not fixed — WORSE** |
| insider-threat-departing-employee | `{"ip": "employee_workstation_ip"}` | `{}` | **not fixed — WORSE** |

**4/9 fixed, 2/9 unchanged in severity, 3/9 made worse.** The "worse" cases are not a scoring
nuance: `args: {}` means `preview_tool("block_ip", {})`, which raises the exact same uncaught
`TypeError: block_ip() missing 1 required positional argument: 'ip'` as the original
`malware-keylogger` crash — confirmed directly against `preview_tool`. Before the fix, these three
scenarios had a placeholder string that at least got caught cleanly by IP-format validation
(`"Invalid IP address: ..."`, no crash); after the fix, they crash the graph instead. Read
literally, the prompt fix could raise the crash-classified count from 1 to as many as 4 — it
partially worked (the model now omits the action entirely in 4/9 cases) but for the cases where it
didn't fully work, it pushed the model toward *omitting the argument* rather than *inventing a
value*, which is worse for this specific bug (`preview_tool`'s missing try/except around the
active-tool call) even though it's arguably "more honest" model behavior in isolation.

**Recommendation for Etap 9 (not deferred lightly, given the above):** two changes, in order of
priority — (1) wrap `preview_tool(draft.tool_name, draft.args)` in `propose_actions` in a
try/except so a malformed/incomplete proposal can no longer crash the whole graph regardless of
what the prompt does; (2) add a hard **semantic** validation step in code — check whether a
proposed IP actually appears in this thread's `tool_results`/evidence before the proposal ever
reaches the approval panel — shifting the guarantee from "trust the prompt" to "verify in code,"
the same principle `execute_tool`/`PermissionError` already applies to execution itself.

**Etap 9 update — priority-1 recommendation implemented and verified:** `propose_actions` now
wraps `preview_tool(draft.tool_name, draft.args)` in a try/except (`backend/app/graph/nodes.py`);
a failing preview drops just that one proposal (treated as "no basis, no proposal") instead of
crashing the graph, and the failure is logged with full context (`tool_name`, `args`, exception) —
visible in Langfuse as an errored span nested under `propose_actions`, not only in server logs
(verified: the RunnableLambda wrapper reports `on_chain_error` to the ambient callback handler
even without an explicit `config=` argument). Re-ran all 4 known crash-shaped scenarios through
`eval.run_eval` for real (not a replay) to confirm:

| Scenario | Pattern reproduced this run | Result |
| --- | --- | --- |
| malware-keylogger | proposed nothing at all | `completed`, no crash |
| data-breach-s3-bucket | `args: {}` (the new preview_tool-crashing shape) | `completed`, proposal dropped, warning logged |
| data-breach-db-exfil | `args: {"ip": "nie dotyczy"}` (placeholder, not `{}` this run) | `completed`, caught by existing IP-format validation |
| insider-threat-departing-employee | `args: {"ip": "nie dotyczy"}` (placeholder, not `{}` this run) | `completed`, caught by existing IP-format validation |

**4/4 confirmed: 0% crash rate on this subset**, real Groq calls, not synthetic replays. Two of
the four didn't reproduce the exact `args: {}` shape this time (Groq isn't perfectly deterministic
even at `temperature=0`) — a good outcome regardless, since it shows the fix holds across whichever
failure shape the model actually produces, not just the one originally observed. Also covered by 3
new regression tests in `backend/tests/test_approval_gate.py` (missing required arg, unexpected
arg key, and a mixed batch where one bad proposal doesn't block a good one). The semantic-validation
recommendation (priority 2, checking a proposed IP actually appears in `tool_results`) remains open
— see `docs/etap9-backlog.md`.

**Live confirmation, unplanned:** the newly-collected 15th scenario
(`ambiguous-encryption-no-ransom-note`, run today with the fixed prompt already in production
code) is genuinely `no_clear_target` and correctly proposed no action at all — one real production
data point in the fix's favor, on top of the 4/9 replayed successes above. It's also the reason
the main table's groundless-action-rate denominator is 11 rather than 10 (10 groundless out of 11
no-clear-target scenarios, since this one is a correct negative).

### Citation recall — report_llm prompt experiment

`report.py` now annotates each plan step shown to `report_llm` with its already-confirmed citation
marker (e.g. "this step is already confirmed to cite [4]; reuse that marker"). Measured by
replaying just the `report` LLM call on 5 scenarios with citation-bearing plan steps, using each
scenario's stored classification/plan/tool_results/retrieved_chunks:

| Scenario | Before | After |
| --- | --- | --- |
| data-breach-db-exfil | no citation | cited [1, 2] |
| ransomware-fileserver | no citation | cited [1, 5] |
| dos-application-layer | no citation | cited [2, 3] |
| phishing-mass-campaign | no citation | cited [1, 3] |
| phishing-single-user | no citation | cited [2] |

**5/5 fixed, 0/5 before** — a clean, unambiguous result at this sample size. **Live confirmation,
unplanned:** the 15th scenario, run today with the fixed `report.py` already in production code,
spontaneously cited `[5]` in its "Plan dalszej diagnostyki" section — the first (and, in the main
14-scenario history, only) scenario in the whole dataset to cite anything organically, which is
exactly why the main table's report-citation-recall metric moved from 0% to 7% (1 of 14 reports).
Both the isolated replay experiment and this one real run point the same direction; the fix is
kept as shipped.

## Scope decisions (this stage measures and decides — it does not fix everything)

Per the Etap 8 brief, each finding below is either fixed now (Part D, gated on the numbers above — see the project's commit history for exactly what changed and why) or deliberately deferred. Deferring is a scope decision, not an oversight:

- **Candidates for Part D, gated on the numbers above**: ZNALEZISKO #9 (plan padding), #10 (frontend stepper), #11 (groundless action rate), #12 (raw repr() in the report's Podjęte działania section), and the citation-recall prompt experiment for #7.
- **Deferred to Etap 9 (evaluation-driven backlog, not abandoned)**: report faithfulness (ZNALEZISKO #5/#6) beyond the flagging done above, language consistency across nodes (ZNALEZISKO #8), and expanding Part C's sample size before committing to a model change.
- **Deferred to Etap 10 (observability)**: resuming a `failed` thread (ZNALEZISKO #1), structured token/cost tracking in production (this eval harness is a one-off script, not a standing observability pipeline — that's Langfuse's job).
