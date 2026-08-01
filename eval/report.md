# Etap 8 — Evaluation report

Scenarios: 6 run, 1 ended in an uncaught error. **Partial dataset: 6 of 15 planned scenarios.** The remaining ones were blocked by Groq's daily token quota (ZNALEZISKO #4) and are meant to be added with `eval.run_eval --resume`, after which this report should be regenerated — treat the numbers below as directional, not final.

## Metrics

| Metric | Value | Recommendation |
| --- | --- | --- |
| Classification accuracy (exact) | 100% | no action |
| Classification accuracy (incl. reasonable neighbor) | 100% | informational |
| Severity in expected range | 100% | informational |
| Citation recall — final report (ZNALEZISKO #7) | 0% | Etap 9 (prompt fix candidate) |
| Citation recall — plan (contrast) | 80% | no action, already works |
| Citation precision | n/a | expected ~100%, see note below |
| Groundless action rate (ZNALEZISKO #11) | 100% | fix now (Part D) |
| Plan padding (mean fraction generic in steps 5+) | 90% | Etap 9 |
| Token cost per scenario (median / p90) | 10770 / 18974 | capacity planning |
| Full runs fitting in 100k tokens/day | 9 | capacity planning |

## Interpretation

### Classification accuracy
5 scenarios scored. Exact-category accuracy 100%, rising to 100% when a defensible neighbor category (e.g. ransomware/malware) counts as correct. Severity landed in the expected range 100% of the time. The ambiguous scenario hasn't been run yet in this dataset.

### Citations — report vs. plan (ZNALEZISKO #7, narrowed)
The final report cited at least once in 0% of scenarios, vs. 80% for the plan panel's own citations. This gap is the actual finding: the same citation *data* (plan.steps[].citations, retrieved_chunks) is available to both, but report_llm doesn't reliably use [n] markers while the plan mechanism (rendered by the frontend, not an LLM decision) does. No [n] markers were found anywhere, so precision isn't measurable this round — expected to be ~100% by construction (report.py's whitelist already strips anything invalid before this measurement ever sees it), so this confirms the mechanism works rather than revealing something new; the low marker COUNT is the real signal, not the precision percentage.

### Groundless action rate (ZNALEZISKO #11)
100% of the 4 no-clear-target scenarios still got a proposed action — but this is three genuinely different failure modes, not one, and blending them into a single rate would hide which ones actually matter:

- **Uncaught crash** — propose_actions raises before anything is even captured — 1:
  - `malware-keylogger` (error): `TypeError: block_ip() missing 1 required positional argument: 'ip'`
- **Placeholder string** — caught by plain IP format validation — 2:
  - `phishing-single-user` (completed): `{'ip': 'nie dotyczy'}`
  - `phishing-mass-campaign` (completed): `{'ip': 'link_domain_ip_address'}`
- **Looked like a real IP** — caught only because it happened to land in a reserved/test range, not because anything detected it was fabricated — 1:
  - `ransomware-fileserver` (completed): `{'ip': '203.0.113.5'}`

The **looked_valid_but_reserved_range** case (1) is the one that actually matters most: it's the closest real occurrence to what ZNALEZISKO #11 originally warned about — 'model mógłby podstawić syntaktycznie poprawny, ale merytorycznie zmyślony adres IP' — a fabricated-looking IP that isn't an obvious placeholder like 'nie dotyczy'. It was only caught because it happened to fall in a reserved range (RFC 5737); a fabricated *public-looking* IP would sail straight through every existing check and reach the approval panel looking legitimate.

### Plan padding (ZNALEZISKO #9)
Across 5 plans with 5+ steps, a mean of 90% of steps from position 5 onward share no specific content word with the original incident description — i.e. they don't reference anything concrete from the case (no server name, filename, IP), unlike the earlier, concrete steps. Consistent with the acceptance-session observation.

### Faithfulness of the Executive summary (ZNALEZISKO #5)
Checked 3 of 5 eligible scenario(s) successfully (2 check(s) failed — see note below); 3 flagged at least one sentence stating something as certain that the clarification answers explicitly marked unknown. This is a list for human review, not an automatic verdict:

- **malware-worm-smb**:
  - "Zespół sieciowy nie potwierdził jeszcze, czy adres IP jest legalnym klientem czy atakującym."
- **ransomware-ssh-bruteforce**:
  - "Serwer aplikacyjny web02 padł ofiarą ataku ransomware"
  - "Zespół bezpieczeństwa znalazł w logach systemowych serię nieudanych prób logowania SSH"
  - "za dnia serwer był w pełni sprawny"
- **phishing-mass-campaign**:
  - "Zespół bezpieczeństwa otrzymał kilkanaście zgłoszeń od pracowników dotyczących tej samej wiadomości phishingowej"
  - "Na razie nie potwierdzono, czy ktokolwiek z pracowników faktycznie wprowadził swoje dane na tej stronie"

**Note**: 2 check(s) failed deterministically (3 identical retries all failed the same way) for **phishing-single-user**, **ransomware-fileserver** — llama-3.1-8b-instant emitted its tool call as literal text instead of a parseable response for these specific inputs. A data point on 8B's structured-output reliability, relevant to the Part C discussion below.

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

## Scope decisions (this stage measures and decides — it does not fix everything)

Per the Etap 8 brief, each finding below is either fixed now (Part D, gated on the numbers above — see the project's commit history for exactly what changed and why) or deliberately deferred. Deferring is a scope decision, not an oversight:

- **Candidates for Part D, gated on the numbers above**: ZNALEZISKO #9 (plan padding), #10 (frontend stepper), #11 (groundless action rate), #12 (raw repr() in the report's Podjęte działania section), and the citation-recall prompt experiment for #7.
- **Deferred to Etap 9 (evaluation-driven backlog, not abandoned)**: report faithfulness (ZNALEZISKO #5/#6) beyond the flagging done above, language consistency across nodes (ZNALEZISKO #8), and expanding Part C's sample size before committing to a model change.
- **Deferred to Etap 10 (observability)**: resuming a `failed` thread (ZNALEZISKO #1), structured token/cost tracking in production (this eval harness is a one-off script, not a standing observability pipeline — that's Langfuse's job).
