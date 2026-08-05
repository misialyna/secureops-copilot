# SecureOps Copilot

[![CI](https://github.com/misialyna/secureops-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/misialyna/secureops-copilot/actions/workflows/ci.yml)

AI agent supporting security incident analysis: classifies incoming reports, retrieves procedural
knowledge with citations (RAG), asks clarifying questions when information is missing, plans
diagnostics, and uses read-only tools (log analysis, PCAP, MITRE ATT&CK). It pauses before any
action requiring human approval and generates a final report.

## Development

- Tests (fast, what CI runs): `uv run pytest -m "not slow"`
- Tests (everything, including the RAG integration test — requires a built index, see below): `uv run pytest`
- Lint: `uv run ruff check .` (fix: `uv run ruff check --fix .`)
- Dev server: `uv run uvicorn app.main:app --reload --app-dir backend`

## Frontend

A React + TypeScript + Vite "analyst console" (`frontend/`, dark theme, no client-side router —
a single page keyed on `thread_id`) covers the full incident lifecycle: submitting a report,
answering clarifying questions, uploading evidence, reviewing the diagnostic plan, approving or
rejecting proposed actions (with a preview of the actual generated commands), and reading the
final report. `thread_id` is kept in the URL (`?thread=...`), so refreshing the page mid-session
restores exactly where it left off.

![New incident screen — description, evidence upload, and the stage stepper](docs/screenshot-new-incident.png)

<details>
<summary>More screenshots (approval panel, final report)</summary>

![Approval panel with the generated block_ip commands previewed before any decision](docs/screenshot-approval.png)
*Approval panel — the analyst sees the actual ufw/iptables/nft commands before approving or rejecting.*

![Rendered final incident report with the diagnostic plan and audit log](docs/screenshot-report.png)
*Diagnostic plan, audit log, and the final Markdown report for a completed incident.*

</details>

### Dev mode (two processes)

```bash
# terminal 1 — backend
uv run uvicorn app.main:app --reload --app-dir backend

# terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite's dev server proxies `/incidents`, `/search`, and `/health` to
`http://127.0.0.1:8000` (see `frontend/vite.config.ts`), so the frontend code always calls the API
with relative paths — no CORS configuration needed on the client side (the backend's
`CORSMiddleware` allows the Vite origin regardless, for direct API calls e.g. from `/docs`).

### Production mode (one process)

```bash
cd frontend
npm run build   # -> frontend/dist
cd ..
uv run uvicorn app.main:app --app-dir backend
```

With `frontend/dist` present, FastAPI serves it directly at `/` (`StaticFiles`, `html=True`) —
the API keeps all its existing paths (`/incidents`, `/health`, ...) untouched, since the static
mount is registered last and only ever catches requests no API route already matched. If
`frontend/dist` doesn't exist (e.g. a fresh checkout before running `npm run build`), the mount
is skipped entirely rather than failing at startup.

## Knowledge base

The RAG knowledge base is built from two public U.S. government incident-response documents,
listed in [`backend/app/rag/sources.py`](backend/app/rag/sources.py):

- NIST SP 800-61 Rev. 3 — *Incident Response Recommendations and Considerations for
  Cybersecurity Risk Management*
- CISA — *Federal Government Cybersecurity Incident and Vulnerability Response Playbooks*

Both are public-domain U.S. government works, downloaded directly from `nvlpubs.nist.gov` and
`cisa.gov`.

### Build the index

```bash
uv run python -m app.rag.ingest
```

This downloads the source PDFs into `knowledge/raw/` (skipped if already present), splits them
into chunks, embeds them with `BAAI/bge-m3`, and stores everything in a local Qdrant index at
`data/qdrant/` (no server required). Neither directory is committed to git — regenerate them
with this command. The first run also downloads the embedding model from Hugging Face
(a few GB), so it takes a few minutes; later runs are fast since both the PDFs and the model
are cached.

### Search

With the index built, either query it directly in Python:

```python
from app.rag.retriever import KnowledgeRetriever

results = KnowledgeRetriever().search("ransomware containment steps", top_k=5)
```

or start the dev server and hit the temporary `/search` endpoint in the browser, e.g.
`http://localhost:8000/search?q=ransomware+containment+steps&top_k=5` (also works with
non-English queries, e.g. `kroki+powstrzymania+ransomware`, since bge-m3 is a multilingual model).

## Agent graph

The core agent is a [LangGraph](https://langchain-ai.github.io/langgraph/) state machine
(`backend/app/graph/`) that classifies an incident report, asks at most one round of clarifying
questions if key details are missing, retrieves relevant procedure excerpts, decides which
read-only investigation tools to run against any uploaded evidence, produces a diagnostic plan
grounded in both the procedure excerpts and the tools' findings, and finally decides whether that
plan justifies proposing *active* actions (e.g. blocking an IP) — which always pause for human
approval before anything is executed (see "Human-in-the-loop approval" below). Classification,
tool selection, planning, and the approval proposal all use Groq (`llama-3.3-70b-versatile`),
with a small retry (3 attempts, short backoff) around the structured-output calls for the
occasional malformed-JSON `tool_use_failed` response.

```mermaid
flowchart TD
    START((start)) --> classify[classify]
    classify -->|missing info, not asked yet| clarify["clarify (interrupt)"]
    classify -->|complete, or already asked once| retrieve[retrieve]
    clarify -->|resume with answers| classify
    retrieve --> tools["tools (bind_tools, max 5 calls)"]
    tools --> plan[plan]
    plan --> propose["propose_actions"]
    propose -->|no active action justified| report[report]
    propose -->|action(s) proposed| gate["approval_gate (interrupt)"]
    gate -->|resume with approvals| report
    report --> END((end))
```

Each run is a `thread_id`, persisted via a checkpointer. If `DATABASE_URL` is set, that's
`AsyncPostgresSaver` (production/Neon, or a local docker-compose Postgres — see "Database" below);
otherwise it falls back to `AsyncSqliteSaver` at `data/checkpoints.sqlite` (gitignored, like the
knowledge-base index), which is what tests and CI use so neither needs a running Postgres. Either
way, state is checkpointed to disk after every node — not kept only in memory — so a paused
(interrupted) thread survives a full server restart: resuming with the same `thread_id` after
restarting `uvicorn` picks up exactly where it left off.

Requires `GROQ_API_KEY` set in `.env` (see `.env.example`) and the knowledge-base index already
built (see above).

## Database

By default (no `DATABASE_URL`), the app uses a local SQLite file for graph checkpoints — nothing
to set up. For Postgres (recommended for anything beyond a quick local check, and required in
production), a local Postgres 16 is provided via docker-compose:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Then set in `.env`:

```
DATABASE_URL=postgresql://secureops:secureops@localhost:5432/secureops
```

The checkpointer creates its own tables on startup (`.setup()`), so no manual migration step is
needed. For Neon (or any managed Postgres), use the connection string Neon gives you — if it
doesn't already include `sslmode=require`, the app adds it automatically for any non-local host
(local docker-compose Postgres has no TLS configured, so that host is left alone).

## Agent tools

Evidence files uploaded for an incident (`POST /incidents/{thread_id}/evidence`) are analyzed by
the `tools` graph node, which lets an LLM decide which of the tools below to run and on which
file. `read_only` tools run immediately; `active` tools never do — `execute_tool()` refuses to
run one without an approved `ApprovalDecision`, raising `PermissionError` if called without one.
This check lives in the registry itself, so it holds regardless of what any LLM "wants" to do —
see "Human-in-the-loop approval" below for how an active tool actually gets to run.

| Tool | `risk_level` | What it does |
| --- | --- | --- |
| `log_analyzer` | `read_only` | Auto-detects auth.log/syslog vs. web access log. auth.log: SSH brute force (≥10 failed logins from one IP in 5 min), successful logins from a brute-forcing IP, new accounts/sudo grants. Access log: top IPs, 4xx/5xx per IP, path-scanning, suspicious user agents. |
| `pcap_analyzer` | `read_only` | Offline PCAP analysis (scapy `rdpcap`, 50 MB file limit): packet count/time range, top talker IP pairs, top destination ports, port-scan detection, suspected C2 beaconing (regular-interval connections to one external IP), suspicious DNS queries (long/repeated domains). |
| `attack_lookup` | `read_only` | Looks up a MITRE ATT&CK technique by ID (e.g. `T1110`) or keyword — name, tactic(s), a short description, and known log/data sources for detecting it. Parsed lazily from the `enterprise-attack.json` STIX bundle and cached in memory. |
| `block_ip` | `active` | Proposes host-firewall commands (ufw, iptables, nft) to block an IP, plus a rollback command — never executes anything itself. Refuses private/loopback/link-local/documentation-range addresses (almost always an operational mistake, not a real attack source). |

Findings that reach an LLM prompt (e.g. sample log lines, queried domains) are always wrapped in
`<untrusted_evidence_data>...</untrusted_evidence_data>` tags in the `plan` prompt, with an
explicit system instruction to treat that content strictly as data — never as instructions —
since it may have been crafted by an attacker (prompt-injection defense).

## Human-in-the-loop approval

After planning, `propose_actions` decides whether the plan and findings justify any `active`
action (e.g. blocking a confirmed brute-force IP). If it proposes nothing, the run finishes
immediately. If it proposes one or more actions, `approval_gate` pauses the graph
(`status: "awaiting_approval"`) with the exact list an analyst must approve or reject — nothing
runs until then, and `execute_tool()` enforces that independently of the LLM.

```mermaid
sequenceDiagram
    participant Analyst
    participant API as FastAPI
    participant Graph as LangGraph (propose_actions / approval_gate)
    participant DB as Checkpointer (Postgres/SQLite)

    Analyst->>API: POST /incidents {description}
    API->>Graph: ainvoke()
    Graph->>Graph: classify -> retrieve -> tools -> plan -> propose_actions
    Graph-->>DB: checkpoint after every node
    Graph-->>API: interrupt({proposed_actions: [...]})
    API-->>Analyst: status="awaiting_approval", proposed_actions=[...]

    Note over Analyst,DB: analyst reviews block_ip commands, effect, rollback —<br/>server may restart here, nothing is lost

    Analyst->>API: POST /incidents/{id}/resume {approvals: [...]}
    API->>Graph: ainvoke(Command(resume=approvals))
    Graph->>Graph: approval_gate matches each approval to its action_id
    Graph->>Graph: approved -> execute_tool(); rejected -> audit only, no execution
    Graph->>Graph: report (writes the final Markdown report, see below)
    Graph-->>API: status="completed", audit_log=[...], report=markdown
    API-->>Analyst: firewall commands (if approved) + full audit log + report
```

**Resume payload shape.** `POST /incidents/{thread_id}/resume` takes one body with two optional,
mutually-exclusive fields — `answers` (for `status: "awaiting_clarification"`) or `approvals`
(for `status: "awaiting_approval"`), and rejects a request that sets both or neither. A single
endpoint was chosen over two (e.g. a separate `/approve`) because both cases are the exact same
underlying operation — resuming a paused LangGraph thread with a value — and the caller already
knows which shape to send from the `status` field of the previous response; splitting it into
two endpoints would just duplicate the same `ainvoke(Command(resume=...))` plumbing twice.

Each `ApprovalDecision` is matched to its `ProposedAction` by `action_id` (not by list position),
and every proposed action gets an `AuditEntry` in `audit_log` — approved-and-executed, rejected,
or (if the client's `approvals` list simply omits an action) treated as not-approved by default,
so nothing is silently dropped from the trail.

## Incident report

The last graph node, `report` (`backend/app/graph/report.py`), always runs — whether or not any
active action was proposed — and writes a Markdown report **in the same language as the original
incident description**, with six fixed sections: Executive summary, Klasyfikacja i ocena,
Ustalenia, Podjęte działania, Plan dalszej diagnostyki, Zalecane dalsze ustalenia.

Citations are handled defensively: the LLM may only cite `[n]` markers from a whitelist *built by
code* (every `(source_id, page)` pair already present in `retrieved_chunks` or attached to a plan
step's citations — the LLM never chooses the numbering). After generation, any `[n]` marker the
LLM used that *isn't* in that whitelist is stripped out and recorded as a warning in
`report_warnings`, and the `## References` section itself is appended by code, listing only the
citations actually left in the text — never generated by the LLM, so it can't be desynced from
what's really cited.

Example excerpt (English incident, for a brute-force scenario with an approved `block_ip`):

```markdown
## Executive summary
Ataki typu brute-force wobec serwera web01 zakończyły się udanym logowaniem na konto root oraz
utworzeniem nowego konta z uprawnieniami sudo. Zablokowano adres IP odpowiedzialny za atak po
zatwierdzeniu przez analityka; zalecana jest dalsza analiza w celu potwierdzenia zakresu incydentu.

## Klasyfikacja i ocena
Kategoria: unauthorized_access, waga: high, pewność: 0.90 — powtarzające się nieudane logowania
SSH zakończone udanym logowaniem wskazują na nieautoryzowany dostęp.

## Ustalenia
Z adresu 45.83.65.12 odnotowano 10 nieudanych prób logowania w ciągu 5 minut, po których nastąpiło
udane logowanie na konto root [1]. Utworzono nowe konto `svc-backup` z uprawnieniami sudo.

## Podjęte działania
Zaproponowano zablokowanie adresu 45.83.65.12 (`block_ip`) — zatwierdzone przez analityka i
wykonane; wygenerowano gotowe polecenia ufw/iptables/nft.

...

## References

[1] CISA — Federal Government Cybersecurity Incident and Vulnerability Response Playbooks — page 12 (source_id: `cisa-ir-vr-playbooks`)
```

Fetch it via `GET /incidents/{thread_id}/report` → `{"markdown": "...", "generated_at": "...", "warnings": [...]}`, or read `report`/`report_warnings` directly off the main `/incidents/{thread_id}` response once `status` is `"completed"`.

### Full cycle example

Start the dev server, then:

```bash
# 1. Submit an incomplete incident report
curl -s -X POST localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{"description": "Found repeated SSH login failures on our web server"}' | python3 -m json.tool
# -> {"thread_id": "...", "status": "awaiting_clarification",
#     "pending_questions": ["Which systems/hosts are affected?", ...]}

# 2. Upload the auth.log evidence for this incident (see backend/tests/test_firewall.py /
#    test_log_analyzer.py for a sample crafted brute-force auth.log)
curl -s -X POST localhost:8000/incidents/<thread_id>/evidence \
  -F "file=@auth.log" | python3 -m json.tool
# -> {"thread_id": "...", "filename": "auth.log", "size_bytes": ...}

# 3. Answer the clarifying questions (echo the exact question strings back as keys) —
#    this resumes the graph, which runs the tools node against auth.log, plans, then
#    decides whether to propose an active action
curl -s -X POST localhost:8000/incidents/<thread_id>/resume \
  -H "Content-Type: application/json" \
  -d '{"answers": {"Which systems/hosts are affected?": "web01"}}' | python3 -m json.tool
# -> {"thread_id": "...", "status": "awaiting_approval",
#     "proposed_actions": [{"id": "...", "tool_name": "block_ip",
#                            "args": {"ip": "203.0.113.7"}, "justification": "...", ...}]}

# 4. Approve (or reject) the proposed action by its id
curl -s -X POST localhost:8000/incidents/<thread_id>/resume \
  -H "Content-Type: application/json" \
  -d '{"approvals": [{"action_id": "<id from step 3>", "approved": true,
                       "decided_at": "2026-01-01T00:00:00Z", "comment": "confirmed malicious"}]}' \
  | python3 -m json.tool
# -> {"thread_id": "...", "status": "completed", "classification": {...}, "plan": {...},
#     "audit_log": [{"action": {...}, "decision": {...}, "executed": true,
#                     "result_summary": "Proposed firewall block for 203.0.113.7 ..."}],
#     "report": "## Executive summary\n...", "report_warnings": []}

# 5. Fetch just the report (same content, plus generated_at)
curl -s localhost:8000/incidents/<thread_id>/report | python3 -m json.tool

# 6. Re-check the full result at any time (e.g. after restarting the server)
curl -s localhost:8000/incidents/<thread_id> | python3 -m json.tool
```

A complete report (no missing information) skips straight from `classify` to `retrieve`/`tools`,
and if `propose_actions` proposes nothing, the run finishes as `status: "completed"` without ever
pausing for approval — `report` still runs either way, so the final response always includes a
Markdown report.

## Observability

Every `graph.ainvoke` call (`/start` and `/resume`) is traced to [Langfuse](https://langfuse.com)
via LangChain's callback mechanism, if configured — entirely optional, same pattern as the
Postgres checkpointer: the app starts and runs fine with no Langfuse account at all.

**Connect your own account:**

1. Create a free project at [cloud.langfuse.com](https://cloud.langfuse.com) (EU) or
   [us.cloud.langfuse.com](https://us.cloud.langfuse.com) (US).
2. Copy its API keys into `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or the us.cloud.langfuse.com host, matching your project's region
   ```
3. Start the app — the startup log confirms which path was taken:
   `Langfuse observability enabled (host=...)` or `Langfuse disabled: ... not set.`

**What gets logged.** Each of the two `graph.ainvoke` call sites (`backend/app/main.py`) merges
in `get_langfuse_config(thread_id, ...)` (`backend/app/observability.py`), which attaches a
`CallbackHandler` plus `metadata={"langfuse_session_id": thread_id}`. LangGraph's node names
become span names automatically — no per-node wiring needed — so a single trace shows every node
(`classify`, `retrieve`, `tools`, `plan`, `propose_actions`/`approval_gate`, `report`) as a nested
span with its own input/output, token counts, and latency. Every `ainvoke` call for the same
incident (the initial `/start`, plus any `/resume` after a clarification or approval interrupt)
shares the same `thread_id`, so Langfuse groups them under one **session** — verified live end to
end: three separate calls for one incident (classify+clarify, retrieve/tools/plan/propose,
approval+report) all appeared under one session in the UI.

![Example Langfuse trace for one incident session](docs/screenshot-langfuse-trace.png)
*Placeholder — replace with your own screenshot after connecting an account.*

**Known limitation: "Total cost" shows $0.00.** Token counts on each `ChatGroq` generation span
are correct (verified directly via Langfuse's public API — `usage`/`usageDetails` show real
input/output/total token counts), but the cost in USD stays zero. Langfuse only ships built-in
per-token pricing for OpenAI, Anthropic, and Google models; Groq isn't in that list, so it can't
price `llama-3.3-70b-versatile` even though it has everything it needs (token counts + model name)
to do so. Fix (a Langfuse **project** setting, not a code change): add a custom model definition
under Project Settings → Models with Groq's actual per-token price (currently $0.59 / 1M input,
$0.79 / 1M output for this model) — user-defined models take priority over Langfuse's built-in
list. Left as a manual step rather than automated here, since it's account configuration, not
application behavior.

## Evaluation

`eval/` is a synthetic-incident evaluation harness (Etap 8) — 15 hand-written scenarios covering
all 8 incident categories, run through the real graph against the real Groq API (no mocks), with
metrics computed on the results: classification accuracy, citation recall/precision, a groundless
active-action rate, plan padding, report faithfulness (LLM-assisted, human-reviewed), and token
cost. Full methodology, numbers, and interpretation: [`eval/report.md`](eval/report.md).

Headline numbers (full 15/15 dataset):

- Classification accuracy: **79%** exact, **93%** including a defensible neighbor category.
- Citation recall — the final report cites its sources in **7%** of scenarios, vs. **79%** for the
  diagnostic plan using the same underlying citation data. A prompt fix (feeding `report_llm` each
  plan step's already-confirmed citation marker) measured **5/5 fixed vs. 0/5 before** on a
  replayed subset — the 7% here is the one scenario in the main dataset that already ran with the
  fixed code.
- Groundless active-action rate: **91%** of no-clear-target scenarios still got a proposed
  `block_ip` action. A "no basis, no proposal" prompt fix only partially helped when measured
  before/after: **4/9 fixed, 2/9 unchanged, and 3/9 made worse** — those three now omit the
  required argument entirely instead of inventing a placeholder, which crashes the same unguarded
  code path a different scenario already crashed on. See the report for why a code-level guard,
  not just a prompt change, is the actual fix needed here.
- Token cost: median **~10.4k** tokens/scenario, letting roughly **9** full runs fit in Groq's
  100k-tokens/day free-tier budget for `llama-3.3-70b-versatile`.

**Not part of CI** — it spends real Groq tokens and takes minutes per scenario, so it's a manual,
occasional check rather than something that runs on every push:

```bash
uv run python -m eval.run_eval                    # fresh run, all scenarios
uv run python -m eval.run_eval --resume eval/results/<timestamp>  # continue after a rate-limit stop
uv run python -m eval.metrics --raw-jsonl eval/results/<timestamp>/raw.jsonl --output eval/report.md
```

## Known limitations

**Drafts and evidence files are ephemeral.** Incident drafts (JSON files, created by
`POST /incidents` before analysis starts) and uploaded evidence files live on the container's
local disk, so on the free Hugging Face Spaces tier a Space restart deletes them. Graph state
itself — sessions, checkpoints, the audit log — is safe in Postgres and survives restarts; only
the pre-analysis draft window is at risk, and in practice that window is a matter of minutes
between creating a draft and calling `POST /incidents/{thread_id}/start`. This is an accepted
trade-off for a demo deployment. In production: drafts would move to a Postgres table, and
evidence files to object storage (e.g. S3) referenced from the database.

**No authentication.** The app has no auth layer — it's a public demo, and `thread_id` is the only
"secret" protecting a session. Also a deliberate scope cut for this stage; a production deployment
would put an auth layer in front of it.

**A thread can end up `status: "failed"`.** If a node fails after the last interrupt has already
been cleared (most commonly: Groq's rate limit, which `with_retry` deliberately does not retry —
see `app/graph/retry.py`), there is no interrupt left to resume and no report to show, so the API
reports `"failed"` rather than a misleading `"completed"` with an empty report. Classification,
plan, and the audit log up to that point are preserved and still returned. There is currently no
way to resume a `"failed"` thread from where it stopped — starting a new incident is the only
option. A proper recovery path (re-running just the failed node from its last good checkpoint) is
planned for the observability stage, alongside the Langfuse integration, where failures like this
will need to be traced anyway.

**No automated tests for frontend interaction logic.** There is no test harness for the frontend
(no Vitest/React Testing Library installed) — a deliberate, deferred decision from Etap 7 (the UI
was still expected to change; see the CI section). This means things like `useIncidentSession`'s
`reset()` (the "Nowe zgłoszenie" navigation) are currently verified only by hand, not by an
automated test. Component/interaction tests are planned for the evaluation stage alongside E2E
coverage, not added ad hoc per feature.
