# Bupa CareFlow V2

V2 of the CareFlow care-coordination prototype: **persistent SQLite storage**, **dual-mode patient data ingestion**, and **auditable patient-priority management**.
All data is **fictional**. Notifications are **simulated**. AI is **advisory only** (deterministic, template-based – no LLM).

## Run
```bash
./run.sh                 # = python3 -m backend.server   → http://127.0.0.1:8787
```
Needs Python 3.10+ (standard library only for the app). Optional for PDFs: `pdftotext`/`pdftoppm` (poppler) and `tesseract` for scanned-PDF OCR; `pypdf` is used as a fallback.
First start creates and seeds `backend/database/careflow_v2.db`. Later starts keep it (never recreated). Demo password for every account: `careflow-demo`
(Priya Nair – coordinator, Dr. Sarah Wilson – doctor, Marcus Reid – administrator; pick a role on the login screen).

## Layout (V1 is a separate project and is not modified)
```
backend/  server.py (HTTP API) · db.py (connection, FK ON, migrations) · migrations/001_init.sql, 002_remove_registration.sql · mapping.py (rows ⇄ UI state)
          seed.py + seed/seed_data.json (Method A) · ingest.py + ingest_api.py (Method B) · priority.py (decision 3)
          database/careflow_v2.db · uploads/ (preserved originals) · sample_uploads/ (demo CSV/JSON/PDF)
frontend/ src/*.js,*.css  →  ./build.sh  →  dist/index.html   (served by the backend)
tests/    test_backend.py · ui_acceptance.js · e2e_v1_flows.js (+ run_e2e_flows.sh)
```
Config: `CAREFLOW_V2_DB`, `CAREFLOW_V2_UPLOADS`, `CAREFLOW_V2_PORT`, `CAREFLOW_V2_HOST`, `CAREFLOW_V2_MAX_UPLOAD`.

## Decision 1 – SQLite
Relational schema with primary/foreign keys (`PRAGMA foreign_keys=ON` on every connection), versioned migrations (`schema_migrations`), WAL mode.
Tables include patients, allergies, medications, diagnoses, care_plans, medical_history, appointments, diagnostic_tests (+values), referrals, prescriptions, consultations, tasks (+events), reminders, communications, notifications, audit_log, documents, ingestion_batches/records, priority_history.
The browser holds no patient database (only a session token in sessionStorage). The UI keeps working state in memory and **writes every change through `/api/sync` into SQLite**.

## Decision 2 – Ingestion
* **Method A:** seeded synthetic data (15 patients with different journeys and care-gap scenarios).
* **No manual registration:** the Patient Registration screen was removed. New patients are created only through Method B below (or the seed); `/api/sync` rejects any attempt to create a patient. Migration `002_remove_registration` drops the old registration-drafts table.
* **Method B:** *Data Import* screen (Care Coordinator only): upload CSV / JSON / PDF → validate type/size/content → extract (CSV/JSON parse; PDF text layer, `pypdf`, or OCR) → map → match patient (**ID first**) → duplicate checks → **review/edit** → manual decision for uncertain matches → **confirm** → saved in one transaction. Originals, SHA-256, uploader and per-record outcomes are preserved; failures are listed, never dropped. Imported records feed profiles, care-gap detection and the AI assistant.
* CSV/JSON: use `record_type` = patient | consultation | test | appointment | referral | medication | allergy | history | task (JSON can also use top-level arrays such as `"consultations": [...]`). Dates: `YYYY-MM-DD` or `DD/MM/YYYY` (UK order).
* Merge rule for an existing patient: blank fields are completed and list items added; **existing values are never overwritten**.

## Decision 3 – Priority
Care Coordinator (any patient) and Doctor (own patients) can change priority: dropdown → **mandatory comment** → old/new review → confirm. Each change updates `patients.priority` and appends to `priority_history` (patient, previous, new, comment, user, role, time). History is **immutable** (DB triggers block UPDATE/DELETE). The care-gap engine and AI only *suggest* a priority; they never write it. The generic sync API ignores priority fields; administrators get 403.

## Tests (all were executed – see the delivery notes)
```bash
python3 tests/test_backend.py      # 88 backend checks (real server, temp DB)
node tests/ui_acceptance.js        # 46 browser checks  (needs playwright + Chrome)
tests/run_e2e_flows.sh             # 29 V1 workflow checks re-run on V2 + SQLite
```

## Known limits
Prototype-grade auth (shared demo password, 12 h bearer sessions, no TLS); single-writer SQLite; OCR quality depends on the scan; PDF field extraction is rule-based (labels such as "Patient ID:", "Report Type:", "Report Date:", "Findings:"); no real notification delivery; not a medical device and not connected to any healthcare system.
