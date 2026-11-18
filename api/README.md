# CareFlow V3 – API and web app

Runs alongside the V2 prototype (`backend/`, `frontend/`), which is unchanged and stays as the reference.

| Part | Stack | Folder |
|---|---|---|
| API | FastAPI · SQLAlchemy 2 · Alembic · Pydantic · argon2 | `api/` |
| Database | PostgreSQL (production) · SQLite (zero-install default for development and tests) | – |
| Web | React 19 · TypeScript · Vite · React Router · TanStack Query | `web/` |

## Run locally (Windows PowerShell)
```powershell
# API  → http://127.0.0.1:8000  (interactive docs: /api/docs)
cd api
py -3.12 -m venv .venv; .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\alembic upgrade head        # create / upgrade the schema
.venv\Scripts\python -m app.seed          # optional: staff accounts + settings only (the API also does this on first start) – NO patients
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# Web  → http://127.0.0.1:5173  (proxies /api to :8000)
cd web
npm install
npm run dev
```
Demo sign-in: any seeded account email (shown on the sign-in page in development), password `careflow-demo`.

**No patient data is preloaded.** On the sign-in screen choose *Demo data to show after sign-in*:
`Keep current data` (default once data exists) · `Empty` · `Baseline` · `Baseline + Escalation` · `… + Recovery` · `All demo datasets` · `V2 demo set (15 patients)`.
Any choice other than *Keep* **replaces all patient-related data** (patients, records, tasks, alerts, imports, audit and priority
history) with exactly that scenario, loaded through the normal import pipeline (`app/demo_data.py`, `POST /api/demo/load`).
This exists only in demo mode: it is disabled when `CAREFLOW_ENV=production` or `CAREFLOW_DEMO_MODE=false`. During the reset the
append-only guard on `priority_history` is lifted inside the same transaction and restored before it commits.
For PostgreSQL see `docker-compose.yml` and `api/.env.example`.

## Tests
```powershell
cd api; .venv\Scripts\python -m pytest        # 164 tests: auth, scoping, priority, immutability, workflows, import, care gaps, jobs, dashboard, demo, assistant, agents
cd web; npm run build                          # type-check + production build
```

## What changed from V2
* **Server owns the data and the rules.** No `/api/state` dump and no generic `/api/sync`: each screen calls specific endpoints that validate input, check permissions and write the audit log in the same transaction.
* **Access control in queries.** Doctors only ever receive their own patients (others → 404), coordinators all active patients, administrators no patient records.
* **Sessions:** opaque token in an `HttpOnly`, `SameSite=Lax` cookie (never readable by JavaScript), stored hashed, 12 h expiry, revoked on sign-out and on password change. Passwords are argon2 hashes. 5 failed sign-ins per account in 15 min → 429. State-changing requests need `X-Requested-With: careflow` (CSRF defence in depth).
* **Typed schema:** real `DATE`/`TIMESTAMP`/`BOOLEAN`/`JSON` columns, Alembic migrations that run on SQLite and PostgreSQL, and `priority_history` made append-only by database triggers on both.
* **Audit:** sign-in/out, failed sign-ins, viewing a patient record and every priority change are logged by the server.

## API (phase 1)
| Method | Path | Who |
|---|---|---|
| GET | `/api/health` | anyone |
| POST | `/api/auth/login` · `/api/auth/logout` · `/api/auth/change-password` | – / signed in |
| GET | `/api/auth/me` · `/api/users` | signed in |
| GET | `/api/patients?search&department&priority&doctorId&mine&sort&page&pageSize` | coordinator, doctor (scoped) |
| GET | `/api/patients/{id}` | coordinator, doctor (scoped) |
| POST | `/api/patients/{id}/priority` · GET `/api/patients/{id}/priority-history` | coordinator, own-patient doctor |

## API (phase 2 – workflows)
| Method | Path | Who / rule |
|---|---|---|
| GET | `/api/catalog` | reference lists (appointment/test types, slots, task statuses) |
| GET | `/api/appointments?from&to&doctorId&status&patientId` · `/api/appointments/slots?doctorId&date` | coordinator & admin all; doctor own diary + own patients |
| POST | `/api/appointments` | coordinator, doctor – future 30-min slot, no double booking (also a partial unique index) |
| POST | `/api/appointments/{id}/confirm` · `complete` · `miss` · `cancel` · `reschedule` | active appointments only; complete/miss not in the future; cancel needs a reason |
| GET | `/api/tests?stage=requested\|scheduled\|awaiting-result\|review\|reviewed\|all` | coordinator, doctor (scoped) |
| POST | `/api/tests` | doctor, own patient → creates a scheduling task for the coordinator |
| POST | `/api/tests/{id}/schedule` · `complete` | coordinator (scheduling closes the linked task) |
| POST | `/api/tests/{id}/result` | **simulated** result feed (demo) |
| POST | `/api/tests/{id}/review` | patient's or requesting doctor |
| GET / POST / PATCH | `/api/tasks` · `/api/tasks/{id}` | history event + audit on every change; notifications on assignment |
| POST | `/api/patients/{id}/referrals` · `/api/referrals/{id}/status` | Pending → Booked → Completed (or Cancelled) |
| POST | `/api/patients/{id}/consultations` | doctor, own patient – updates care plan / review date, records prescription, optional follow-up task |
| GET / POST | `/api/notifications` · `/{id}/read` · `/read-all` | own notifications only |

Side effects run in the same transaction as the action: audit log, notifications, simulated communications log, and
appointment / test reminders (created and withdrawn; *delivery* moves to the phase 3 scheduler).

## API (phase 3 – import, care gaps, jobs)
| Method | Path | Who / rule |
|---|---|---|
| POST | `/api/ingest/upload` (multipart `file`) | coordinator – CSV / JSON / PDF ≤ 5 MB; rejected and failed files are kept in the history |
| GET · POST · GET | `/api/ingest/demo` · `/api/ingest/demo/{id}/load` · `/api/ingest/demo/{id}/file` | coordinator – one-click demo datasets (dates relative to today) |
| GET | `/api/ingest/batches` · `/api/ingest/batches/{id}` | coordinator – history and review detail |
| PATCH | `/api/ingest/records/{id}` `{fields?, patientId?\|"NEW", decision?}` | edit / link / create / skip, then re-checked |
| POST | `/api/ingest/batches/{id}/confirm` · `/cancel` | per-record savepoints; affected patients are re-scanned for care gaps |
| GET | `/api/documents/{id}/file` | coordinator; doctor for own patients |
| GET | `/api/care-gaps?status&rule&priority&patientId&mine&assignee` | coordinator, doctor (scoped) |
| GET | `/api/care-gaps/summary` | every role (administrators: counts only) |
| POST | `/api/care-gaps/{id}/approve` `{title?, text?, assignee?, due?, priority?}` · `/{id}/dismiss` `{reason}` | coordinator, doctor |
| POST | `/api/care-gaps/scan` | coordinator, admin |
| GET · POST | `/api/jobs` · `/api/jobs/run` | coordinator & admin · admin |

**Care gaps** are stored (`care_gap_alerts`) and synchronised by `services/care_gaps.rescan()`: after every relevant action for that patient,
after an import, on the scheduler, and on demand. Open → Actioned (approved → task) / Dismissed (reason) / Resolved (automatic when the rule
stops firing; re-opens if it fires again). Each patient gets an advisory `suggestedPriority`; the stored priority is never changed by rules.

**Background jobs** (`app/jobs.py`): simulated reminder delivery and a full care-gap scan. No job calls the LLM.
```powershell
# development: runs inside the API process (CAREFLOW_SCHEDULER=embedded, every CAREFLOW_SCHEDULER_INTERVAL_SECONDS=300)
# production / several API instances: CAREFLOW_SCHEDULER=off on the API, plus exactly one worker:
.venv\Scripts\python -m app.worker          # or: python -m app.worker --once
```
PDF import uses `pdftotext` → `pypdf` → OCR (`pdftoppm` + `tesseract`); scanned PDFs need Poppler and Tesseract installed.

## API (phase 4 – AI Care Assistant)
Template-based agents (Context → Care-Gap → Summary → Next-Best-Action) in `services/assistant.py` – **no language model**. Answers use only
records in the user's scope, label every statement (recorded fact / AI suggestion / missing information) and cite numbered sources.
| Method | Path | Notes |
|---|---|---|
| GET · POST · DELETE | `/api/assistant/messages` | the user's own conversation (stored); POST `{text, patientId?}` asks a question |
| GET | `/api/assistant/prompts` | suggested questions |
| GET | `/api/assistant/patients/{id}/summary` | grounded patient summary (audited) – the profile's *AI Summary* tab |
| POST | `/api/assistant/proposals/{id}/approve` · `/reject` | drafted tasks / reminders are created **only** on approval |
Coordinators and doctors only (doctors: own patients; asking about another doctor's actions is refused).

### Care-gap recommendation agent (Google Gemini)
The *Recommended next action* on each care-gap alert is worded by an LLM agent (`services/recommendation_agent.py`, Google `google-genai` SDK).
The rule engine still decides that a gap exists, its priority and its evidence; the agent only writes the recommendation, a one-line
rationale and a task title (structured JSON output), and a person still approves, modifies or dismisses it.
* **Data sent:** de-identified facts only – category, rule, priority, reason, evidence, department, primary condition, the rule's template
  action. No names, IDs, dates of birth or contact details (names/IDs inside rule text are replaced before sending).
* **When: on demand only.** The model is called solely when a person clicks *Generate / Regenerate with AI*
  (`POST /api/care-gaps/{id}/recommendation`) – one click, one request. Scans, imports, demo loads, list views and scheduled jobs never
  call it. Until then the card shows the rule template. Wording is stored on the alert with model and time, and hidden as soon as the
  alert's facts change (`aiStatus: stale`) until someone regenerates it. `aiStatus`: `ready` · `none` (never requested) · `stale` · `withheld` (failed the safety check) · `error` · `off` (no key / switched off).
* **Resilience:** one attempt per model, then the fallback models (`CAREFLOW_GEMINI_FALLBACK_MODELS`) on 404/429/5xx/timeouts; if all
  fail the card shows the rule template ("AI wording unavailable").
* **Configuration:** `CAREFLOW_GEMINI_API_KEY` in `api/.env` (git-ignored – never in code), `CAREFLOW_GEMINI_MODEL`
  (default `gemini-3.5-flash`), `CAREFLOW_LLM_ENABLED`. Tests never call the real model.

### Agent layer (multi-agent phase 1 – `app/agents/`)
Every LLM call in the app goes through one orchestrator; agents are small declarative classes (system prompt, output schema,
`clean()`, `verify()`), registered by name.
| Module | Role |
|---|---|
| `llm.py` | Gemini provider: one structured-output request, model fallback on 404/429/5xx/timeouts, stop on 400/401/403 |
| `privacy.py` | `deidentify()` and `find_leaks()` (patient ID, email, phone, name, date of birth, address – reports kinds, never values) |
| `base.py` | `Agent` base class + registry |
| `limits.py` | kill switch, per-user hourly cap, cooldown for everyone after a 429 on every model |
| `orchestrator.py` | `run()`: switch → limits → privacy check of the input → **one** provider request → `verify()` + output leak check → run log |
| `verifier.py` | **Safety & grounding verifier** (phase 2, code only – no LLM): withholds output that gives clinical advice (diagnosis, interpretation, prescribing, dose / medication changes, emergency referral), sets or changes priority, claims actions or contact attempts not in the facts, mentions dates, values or tests that are not in the facts, leaves a doctor's decision without naming a doctor, contradicts the rule's priority, or runs over 3 sentences |
| `context.py` | **Context agent** (phase 3, code only): the patient's records in the user's scope as numbered, de-identified facts (names/IDs → "the patient", contact details / DOB / address removed from free text, staff names → role, source labels only) plus a fingerprint |
| `testing.py` | `FakeLLM` (pytest fixture `fake_llm`) – tests never touch the network |

**Patient AI summary (phase 3, `services/summary_agent.py`).** On the profile's *AI Summary* tab, *Generate AI summary* runs Context agent →
summary agent (one Gemini request) → verifier. The agent writes an overview (1–3 statements) and the narrative sections; every fact
or suggestion must cite an existing source number, no care gap, pending result / referral or missing-information item may be dropped,
and the phase 2 content checks apply to every statement. Suggested next steps stay rule-based. The summary is stored per patient
(`ai_summaries`, migration 0007) with the Context agent's fingerprint and hidden (`stale`) as soon as the records change.
| Method | Path | Notes |
|---|---|---|
| GET | `/api/assistant/patients/{id}/summary` | template summary (no LLM) + `ai` = stored AI summary state (`ready` / `none` / `stale` / `withheld` / `error` / `off`) |
| POST | `/api/assistant/patients/{id}/summary/ai` | write the AI summary now (one request); 503 off · 429 limit · 502 failed / withheld (template stays) |

**Ask AI in the assistant chat (phase 4, `services/answer_agent.py`).** *Send* keeps the template agents (no LLM). *Ask AI*
(`POST /api/assistant/messages` with `"ai": true`) runs: orchestrator routing (code – a named or selected patient → that patient's
facts incl. rule-based next steps; otherwise the worklist of every patient in scope) → Context (patients become "Patient A, B…",
staff "Staff 1 (doctor)…", the user "you" – in the facts **and** the question) → answer agent (one Gemini request: statements citing
sources + up to 3 drafted tasks / reminders) → verifier (sources and aliases exist, phase 2 content checks on every statement, title and
message; leak checks across every patient in scope). Aliases are mapped back to names only after verification; drafts become
`assistant_proposals` in status *Proposed*. If the agent is off, limited, fails or is withheld, the template answer is returned with a
note – Ask AI never returns an error. Template replies that match no intent offer *Ask AI instead*.
The orchestrator commits before the provider request, so no database transaction is open while waiting for the model.

**Run log** (`agent_runs`, migration 0006): who asked, which agent, status (`ok` / `failed` / `withheld` / `blocked` / `limited` /
`disabled`), model and fallback attempts, error, time taken, hash of the de-identified input. Prompts and outputs are never stored there.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/agents` | availability of each agent and the caller's remaining hourly quota |
| GET | `/api/agents/runs?limit` | own runs (coordinator, doctor); all runs without patient references (administrator) |

Withheld output is never shown or stored on the record; the alert shows `aiStatus: withheld` ("AI wording withheld by the safety check")
with the reasons, the rule template stays, and the reasons are kept in `agent_runs.issues`.

Errors: switched off / no key → **503**; hourly cap or provider cooldown → **429** with `Retry-After`; provider failure or output
withheld by a check → **502**, and the rule template stays on screen. Settings: `CAREFLOW_AGENTS_ENABLED`, `CAREFLOW_AGENTS_DISABLED`,
`CAREFLOW_AGENT_CALLS_PER_USER_PER_HOUR` (30), `CAREFLOW_AGENT_COOLDOWN_SECONDS` (60).

**Removed in phase 4:** Communications, Recovery Tracker and Patient Experience (migration 0004 drops `communications`, `feedback`
and the patient `outcome_*` columns). Call outcomes and manual reminders are recorded in the audit trail / reminders table instead.

## Migration roadmap
1. ✅ Foundation: schema + migrations, auth, access scoping, patients, priority, React shell (Dashboard, Patients, Patient detail).
2. ✅ Appointments, diagnostic tests (request → schedule → result → review), tasks, referrals, consultations, notifications – one endpoint per action, with screens.
3. ✅ Data Import + demo datasets on the server; care-gap rules with stored alerts and advisory suggested priority; scheduler / worker for reminders and scans.
4. ✅ AI Care Assistant (template-based) + AI Summary tab. Communications, Recovery Tracker and Patient Experience removed.
   Still to migrate: Doctor Performance, Executive Overview, Settings / user admin.
5. Production: Docker images, CI, structured logging, HTTPS reverse proxy, backups; replace the in-process login limiter with Redis when running more than one instance.
