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
cd api; .venv\Scripts\python -m pytest        # 87 tests: auth, scoping, priority, immutability, workflows, import, care gaps, jobs, dashboard, demo, assistant
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

**Background jobs** (`app/jobs.py`): simulated reminder delivery and a full care-gap scan.
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
* **When:** automatically in the background for new or changed alerts (after scans, imports, demo loads and on the scheduler), and on
  demand with *Generate / Regenerate with AI* (`POST /api/care-gaps/{id}/recommendation`). Wording is stored on the alert with model and
  time, and hidden as soon as the alert's facts change until it is re-worded.
* **Resilience:** one attempt per model, then the fallback models (`CAREFLOW_GEMINI_FALLBACK_MODELS`) on 404/429/5xx/timeouts; if all
  fail the card shows the rule template ("AI wording unavailable").
* **Configuration:** `CAREFLOW_GEMINI_API_KEY` in `api/.env` (git-ignored – never in code), `CAREFLOW_GEMINI_MODEL`
  (default `gemini-3.5-flash`), `CAREFLOW_LLM_ENABLED`. Tests never call the real model.

**Removed in phase 4:** Communications, Recovery Tracker and Patient Experience (migration 0004 drops `communications`, `feedback`
and the patient `outcome_*` columns). Call outcomes and manual reminders are recorded in the audit trail / reminders table instead.

## Migration roadmap
1. ✅ Foundation: schema + migrations, auth, access scoping, patients, priority, React shell (Dashboard, Patients, Patient detail).
2. ✅ Appointments, diagnostic tests (request → schedule → result → review), tasks, referrals, consultations, notifications – one endpoint per action, with screens.
3. ✅ Data Import + demo datasets on the server; care-gap rules with stored alerts and advisory suggested priority; scheduler / worker for reminders and scans.
4. ✅ AI Care Assistant (template-based) + AI Summary tab. Communications, Recovery Tracker and Patient Experience removed.
   Still to migrate: Doctor Performance, Executive Overview, Settings / user admin.
5. Production: Docker images, CI, structured logging, HTTPS reverse proxy, backups; replace the in-process login limiter with Redis when running more than one instance.
