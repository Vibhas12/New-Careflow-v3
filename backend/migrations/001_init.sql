-- Bupa CareFlow V2 – initial relational schema (SQLite)
-- Foreign keys are enforced per-connection (PRAGMA foreign_keys=ON in db.py).
-- All data in this database is FICTIONAL demonstration data.

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('coordinator','doctor','admin')),
  title TEXT,
  email TEXT,
  phone TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  password_hash TEXT,
  extra_json TEXT
);

CREATE TABLE departments (
  name TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE user_departments (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  department TEXT NOT NULL REFERENCES departments(name),
  PRIMARY KEY (user_id, department)
);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE app_settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE id_sequences (
  prefix TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);

-- ingestion (declared before clinical tables because they reference it) ----------
CREATE TABLE ingestion_batches (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  file_type TEXT,
  size_bytes INTEGER,
  sha256 TEXT,
  stored_path TEXT,
  status TEXT NOT NULL CHECK (status IN ('Rejected','Failed','Needs Review','Ready','Imported','Partially Imported','Cancelled')),
  message TEXT,
  uploaded_by TEXT REFERENCES users(id),
  uploaded_by_name TEXT,
  uploaded_at TEXT NOT NULL,
  confirmed_by TEXT REFERENCES users(id),
  confirmed_at TEXT,
  extraction_method TEXT,
  n_records INTEGER DEFAULT 0,
  n_imported INTEGER DEFAULT 0,
  n_skipped INTEGER DEFAULT 0,
  n_failed INTEGER DEFAULT 0
);

-- patients -------------------------------------------------------------------------
CREATE TABLE patients (
  id TEXT PRIMARY KEY,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  dob TEXT,
  gender TEXT,
  email TEXT,
  mobile TEXT,
  address TEXT,
  ec_name TEXT,
  ec_phone TEXT,
  department TEXT REFERENCES departments(name),
  primary_condition TEXT,
  secondary_conditions TEXT,
  previous_surgeries TEXT,
  family_history TEXT,
  ins_provider TEXT,
  policy TEXT,
  coverage TEXT,
  doctor_id TEXT REFERENCES users(id),
  coord_id TEXT REFERENCES users(id),
  registered_on TEXT,
  review_due TEXT,
  plan_review_due TEXT,
  outcome_status TEXT,
  outcome_note TEXT,
  outcome_date TEXT,
  outcome_by TEXT REFERENCES users(id),
  discharged INTEGER NOT NULL DEFAULT 0,
  draft INTEGER NOT NULL DEFAULT 0,
  -- Current priority. Changed ONLY through the audited priority endpoint (see priority_history).
  priority TEXT NOT NULL DEFAULT 'med' CHECK (priority IN ('high','med','low')),
  priority_updated_at TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  extra_json TEXT
);
CREATE INDEX idx_patients_doctor ON patients(doctor_id);
CREATE INDEX idx_patients_name ON patients(last_name, first_name);

CREATE TABLE allergies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  substance TEXT NOT NULL,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  UNIQUE (patient_id, substance)
);

CREATE TABLE medications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Active',
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  UNIQUE (patient_id, description)
);

CREATE TABLE diagnoses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  UNIQUE (patient_id, description)
);

CREATE TABLE care_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL UNIQUE REFERENCES patients(id) ON DELETE CASCADE,
  plan_text TEXT,
  start_date TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id)
);

CREATE TABLE medical_history (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  event_date TEXT,
  type TEXT,
  title TEXT,
  detail TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id)
);
CREATE INDEX idx_history_patient ON medical_history(patient_id);

-- appointments / tests / referrals / prescriptions / consultations ----------------------
CREATE TABLE appointments (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  doctor_id TEXT REFERENCES users(id),
  dept TEXT,
  appt_date TEXT NOT NULL,
  appt_time TEXT,
  type TEXT,
  status TEXT NOT NULL,
  created_on TEXT,
  notes TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  extra_json TEXT
);
CREATE INDEX idx_appt_patient ON appointments(patient_id);
CREATE INDEX idx_appt_date ON appointments(appt_date);

CREATE TABLE diagnostic_tests (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  ordered_by TEXT REFERENCES users(id),
  ordered_on TEXT,
  scheduled_date TEXT,
  status TEXT NOT NULL,
  completed_on TEXT,
  result_on TEXT,
  reviewed_on TEXT,
  reviewed_by TEXT REFERENCES users(id),
  review_note TEXT,
  abnormal INTEGER NOT NULL DEFAULT 0,
  priority TEXT,
  notes TEXT,
  result_summary TEXT,
  result_source TEXT,
  document_id TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  extra_json TEXT
);
CREATE INDEX idx_tests_patient ON diagnostic_tests(patient_id);

CREATE TABLE test_result_values (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  test_id TEXT NOT NULL REFERENCES diagnostic_tests(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  analyte TEXT,
  value TEXT,
  unit TEXT,
  ref_range TEXT,
  flag TEXT
);

CREATE TABLE referrals (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  referred_to TEXT,
  reason TEXT,
  status TEXT NOT NULL,
  created_on TEXT,
  referred_by TEXT REFERENCES users(id),
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  extra_json TEXT
);

CREATE TABLE prescriptions (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  drug TEXT,
  prescribed_by TEXT REFERENCES users(id),
  rx_date TEXT,
  refill_due TEXT,
  status TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  extra_json TEXT
);

CREATE TABLE consultations (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  doctor_id TEXT REFERENCES users(id),
  consult_date TEXT,
  notes TEXT,
  diagnosis TEXT,
  prescription TEXT,
  plan TEXT,
  follow_up TEXT,
  instructions TEXT,
  created_on TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  extra_json TEXT
);
CREATE INDEX idx_consult_patient ON consultations(patient_id);

-- tasks ------------------------------------------------------------------------------
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
  priority TEXT,
  assignee TEXT REFERENCES users(id),
  created TEXT,
  due TEXT,
  status TEXT NOT NULL,
  kind TEXT,
  source TEXT,
  description TEXT,
  completed_on TEXT,
  alert_id TEXT,
  source_batch_id TEXT REFERENCES ingestion_batches(id),
  extra_json TEXT
);

CREATE TABLE task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  ts TEXT,
  by_name TEXT,
  text TEXT
);

-- communications ------------------------------------------------------------------------
CREATE TABLE reminders (
  id TEXT PRIMARY KEY,
  kind TEXT,
  ref_id TEXT,
  patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
  offset_label TEXT,
  channel TEXT,
  scheduled_for TEXT,
  status TEXT,
  sent_at TEXT,
  label TEXT,
  message TEXT,
  simulated INTEGER NOT NULL DEFAULT 1,
  extra_json TEXT
);

CREATE TABLE communications (
  id TEXT PRIMARY KEY,
  ts TEXT,
  direction TEXT,
  category TEXT,
  recipient TEXT,
  patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
  message TEXT,
  channel TEXT,
  status TEXT,
  sender TEXT,
  simulated INTEGER NOT NULL DEFAULT 1,
  extra_json TEXT
);

CREATE TABLE notifications (
  id TEXT PRIMARY KEY,
  ts TEXT,
  to_user TEXT REFERENCES users(id) ON DELETE CASCADE,
  to_role TEXT,
  title TEXT,
  text TEXT,
  route TEXT,
  patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
  is_read INTEGER NOT NULL DEFAULT 0,
  level TEXT,
  extra_json TEXT
);

CREATE TABLE feedback (
  id TEXT PRIMARY KEY,
  patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
  doctor_id TEXT REFERENCES users(id),
  dept TEXT,
  rating INTEGER,
  recommend INTEGER,
  comment TEXT,
  fb_date TEXT,
  demo INTEGER NOT NULL DEFAULT 1,
  extra_json TEXT
);

CREATE TABLE audit_log (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  user_id TEXT,
  user_name TEXT,
  role TEXT,
  action TEXT NOT NULL,
  patient_id TEXT REFERENCES patients(id) ON DELETE SET NULL,
  entity TEXT,
  detail TEXT,
  extra_json TEXT
);

-- care-gap alert state, AI proposals and chat (advisory data) -------------------------------
CREATE TABLE alert_state (
  id TEXT PRIMARY KEY,
  patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
  status TEXT,
  data_json TEXT
);

CREATE TABLE ai_proposals (
  id TEXT PRIMARY KEY,
  patient_id TEXT REFERENCES patients(id) ON DELETE CASCADE,
  data_json TEXT
);

CREATE TABLE chat_messages (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  data_json TEXT
);

CREATE TABLE ai_meta (
  patient_id TEXT PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE,
  data_json TEXT
);

CREATE TABLE drafts (
  id TEXT PRIMARY KEY,
  data_json TEXT
);

-- documents (preserved originals) ------------------------------------------------------------
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  batch_id TEXT REFERENCES ingestion_batches(id),
  patient_id TEXT REFERENCES patients(id) ON DELETE SET NULL,
  filename TEXT NOT NULL,
  file_type TEXT,
  size_bytes INTEGER,
  sha256 TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  doc_type TEXT,
  extracted_text TEXT,
  extraction_method TEXT,
  uploaded_by TEXT REFERENCES users(id),
  uploaded_at TEXT NOT NULL
);
CREATE INDEX idx_documents_patient ON documents(patient_id);
CREATE INDEX idx_documents_sha ON documents(sha256);

CREATE TABLE ingestion_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL REFERENCES ingestion_batches(id) ON DELETE CASCADE,
  row_no INTEGER,
  kind TEXT NOT NULL,
  raw_json TEXT,
  mapped_json TEXT,
  match_status TEXT NOT NULL CHECK (match_status IN ('matched','new','uncertain','duplicate','invalid')),
  matched_patient_id TEXT REFERENCES patients(id),
  candidates_json TEXT,
  issues_json TEXT,
  decision TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','import','skip')),
  result TEXT CHECK (result IN ('saved','skipped','failed')),
  result_message TEXT,
  saved_entity TEXT
);
CREATE INDEX idx_ing_rec_batch ON ingestion_records(batch_id);

-- priority history: append-only audit trail ----------------------------------------------------
CREATE TABLE priority_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_id TEXT NOT NULL REFERENCES patients(id),
  previous_priority TEXT CHECK (previous_priority IN ('high','med','low')),
  new_priority TEXT NOT NULL CHECK (new_priority IN ('high','med','low')),
  comment TEXT NOT NULL CHECK (length(trim(comment)) >= 5),
  user_id TEXT REFERENCES users(id),
  user_name TEXT NOT NULL,
  user_role TEXT NOT NULL,
  changed_at TEXT NOT NULL
);
CREATE INDEX idx_prihist_patient ON priority_history(patient_id, id);

CREATE TRIGGER priority_history_no_update BEFORE UPDATE ON priority_history
BEGIN SELECT RAISE(ABORT, 'priority_history is immutable'); END;
CREATE TRIGGER priority_history_no_delete BEFORE DELETE ON priority_history
BEGIN SELECT RAISE(ABORT, 'priority_history is immutable'); END;
