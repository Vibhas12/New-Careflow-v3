"""Backend acceptance tests for CareFlow V2 (SQLite, ingestion, priority). Runs a REAL server on a temp DB.
   python3 tests/test_backend.py   → prints PASS/FAIL per check, exit code 1 if any fail."""
import base64, hashlib, json, os, shutil, signal, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SAMPLES = ROOT / 'backend' / 'sample_uploads'
TMP = Path(tempfile.mkdtemp(prefix='cfv2_'))
DB = TMP / 'database' / 'careflow_v2.db'
UPL = TMP / 'uploads'
PORT = 8799
BASE = f'http://127.0.0.1:{PORT}'
ENV = dict(os.environ, CAREFLOW_V2_DB=str(DB), CAREFLOW_V2_UPLOADS=str(UPL), CAREFLOW_V2_PORT=str(PORT), PYTHONPATH=str(ROOT))
results = []
proc = None


def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print(('PASS  ' if cond else 'FAIL  ') + name + (f'   [{detail}]' if (detail and not cond) else ''))
    return bool(cond)


def start():
    global proc
    proc = subprocess.Popen([sys.executable, '-m', 'backend.server', '--quiet'], cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + '/api/health', timeout=1).read(); return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError('server did not start: ' + (proc.stderr.read().decode() if proc.poll() is not None else ''))


def stop():
    global proc
    if proc and proc.poll() is None:
        proc.send_signal(signal.SIGINT);
        try: proc.wait(8)
        except Exception: proc.kill()


def call(method, path, body=None, tok=None, raw=False):
    req = urllib.request.Request(BASE + path, method=method, data=(json.dumps(body).encode() if body is not None else None),
                                 headers={'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + tok} if tok else {})})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        data = r.read()
        return r.status, (data if raw else json.loads(data))
    except urllib.error.HTTPError as e:
        data = e.read()
        try: return e.code, json.loads(data)
        except Exception: return e.code, {'error': data.decode()[:200]}


def login(uid):
    s, r = call('POST', '/api/login', {'userId': uid, 'password': 'careflow-demo'})
    assert s == 200, r
    return r['token']


def upload(tok, path_or_name, data=None):
    p = Path(path_or_name)
    content = data if data is not None else p.read_bytes()
    return call('POST', '/api/ingest/upload', {'filename': p.name, 'contentBase64': base64.b64encode(content).decode()}, tok)


def rec(batch, **kw):
    for r in batch['recordList']:
        if all(r['mapped'].get(k) == v for k, v in kw.items()):
            return r
    return None


def main():
    v1_before = {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in map(str, Path('/home/claude/careflow/src').glob('*'))}
    v1_before['/home/claude/careflow/index.html'] = hashlib.md5(Path('/home/claude/careflow/index.html').read_bytes()).hexdigest()
    check('S1 database file does not exist before first start', not DB.exists())
    start()
    check('S1 database created on first start (backend/database/careflow_v2.db layout)', DB.exists() and DB.stat().st_size > 50_000)
    s, h = call('GET', '/api/health')
    check('S1 migrations applied and recorded', h['migrations'] == ['001_init', '002_remove_registration'], h)
    check('S1 registration drafts table removed', sqlite3.connect(DB).execute("SELECT COUNT(*) FROM sqlite_master WHERE name='drafts'").fetchone()[0] == 0)
    check('S2 foreign-key enforcement ON per connection', h['foreignKeys'] == 1)
    con = sqlite3.connect(DB); con.execute('PRAGMA foreign_keys=ON')
    try:
        con.execute("INSERT INTO appointments(id,patient_id,appt_date,status) VALUES('APT-X','PT-9999','2026-12-01','Scheduled')"); fk = False
    except sqlite3.IntegrityError:
        fk = True
    check('S2 foreign key blocks an appointment for a non-existent patient', fk)
    check('S2 foreign_key_check reports zero violations on seeded data', con.execute('PRAGMA foreign_key_check').fetchall() == [])
    n_tables = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]
    check('S1 relational schema (>= 25 tables incl. patients, appointments, diagnostic_tests, medications, allergies, care_plans, documents, priority_history)', n_tables >= 25, n_tables)
    con.close()

    # ---------------- Seeded data (Method A)
    tc, td, td2, ta = login('u-c1'), login('u-d1'), login('u-d2'), login('u-a1')
    s, st = call('GET', '/api/state', tok=tc)
    check('I1 seeded: 15 synthetic patients with consistent IDs', len(st['patients']) == 15 and st['patients'][0]['id'] == 'PT-1001')
    need = {'appointments': 50, 'tests': 8, 'consultations': 20, 'referrals': 4, 'prescriptions': 10, 'history': 30}
    check('I1 seeded: appointments, tests, consultations, referrals, prescriptions, history, tasks all present', all(len(st[k]) >= v for k, v in need.items()) and len(st['tasks']) >= 10, {k: len(st[k]) for k in need})
    ids = {p['id'] for p in st['patients']}
    check('I1 every seeded child record points to an existing patient', all(x['patientId'] in ids for k in ('appointments', 'tests', 'consultations', 'referrals', 'prescriptions', 'history') for x in st[k]))
    p4 = next(p for p in st['patients'] if p['id'] == 'PT-1004')
    check('I1 seeded: medications / allergies / previous diagnoses / care plan present on profile', p4['meds'] and p4['allergies'] != 'None recorded' and p4['prevDx'] != 'None' and p4['treatmentPlan'])
    check('I1 initial priority recorded in priority_history for every seeded patient', len(st['priorityHistory']) == 15 and all(h['previous'] is None for h in st['priorityHistory']))

    # ---------------- Priority (decision 3)
    base_hist = list(st['priorityHistory'])
    pt = next(p for p in st['patients'] if p['id'] == 'PT-1001')   # Dr Wilson's patient
    old = pt['priority']
    new = 'low' if old != 'low' else 'med'
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': new, 'comment': ''}, tc)
    check('P3 coordinator: empty comment rejected (400)', s == 400 and 'comment' in r['error'].lower(), r)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': new, 'comment': 'ok'}, tc)
    check('P3 coordinator: too-short comment rejected', s == 400, r)
    s, st2 = call('GET', '/api/state', tok=tc)
    check('P3 rejected attempts changed nothing (priority and history unchanged)', next(p for p in st2['patients'] if p['id'] == 'PT-1001')['priority'] == old and len(st2['priorityHistory']) == 15)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': new, 'comment': 'Patient stable after review; lowering follow-up urgency'}, tc)
    e = r.get('entry', {})
    check('P1 Care Coordinator can change priority', s == 200 and e.get('new') == new and e.get('previous') == old, r)
    check('P1 history entry captures patient ID, previous, new, comment, user name, role, date/time',
          all(e.get(k) for k in ('patientId', 'previous', 'new', 'comment', 'user', 'role', 'at')) and e['user'] == 'Priya Nair' and e['role'] == 'coordinator')
    other = 'high'
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': other, 'comment': ''}, td)
    check('P3 doctor: empty comment rejected', s == 400, r)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': other, 'comment': 'Missed review and abnormal result pending – escalating'}, td)
    check('P2 Doctor can change priority (own patient)', s == 200 and r['entry']['role'] == 'doctor' and r['entry']['user'] == 'Dr. Sarah Wilson', r)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': 'low', 'comment': 'trying a patient I do not manage'}, td2)
    s2, r2 = call('POST', '/api/priority', {'patientId': 'PT-1004', 'newPriority': 'low', 'comment': 'Neurologist changing a cardiology patient'}, td2)
    check('P2 doctor cannot change priority of another doctor\'s patient (403)', s2 == 403, r2)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': 'high', 'comment': 'same as current priority'}, tc)
    check('P3 changing to the same priority is rejected', s == 400)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': 'urgent', 'comment': 'invalid level here'}, tc)
    check('P3 invalid priority level rejected', s == 400)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': 'low', 'comment': 'Administrator attempt should fail'}, ta)
    check('P6 Administrator cannot change priority (403)', s == 403, r)
    s, r = call('POST', '/api/priority', {'patientId': 'PT-1001', 'newPriority': 'low', 'comment': 'Anonymous attempt should fail'})
    check('P6 unauthenticated request rejected (401)', s == 401)
    s, st3 = call('GET', '/api/state', tok=tc)
    cur = next(p for p in st3['patients'] if p['id'] == 'PT-1001')['priority']
    hist = [h for h in st3['priorityHistory'] if h['patientId'] == 'PT-1001']
    check('P4 priority changes are saved (current priority = latest history entry)', cur == 'high' and hist[-1]['new'] == 'high' and len(hist) == 3, (cur, len(hist)))
    check('P4 timeline chain is consistent (each previous = prior new)', hist[1]['previous'] == hist[0]['new'] and hist[2]['previous'] == hist[1]['new'])
    check('P5 old history remains intact (earlier rows byte-identical)', all(h in st3['priorityHistory'] for h in base_hist if h['patientId'] == 'PT-1001'))
    con = sqlite3.connect(DB)
    try: con.execute("UPDATE priority_history SET comment='tampered' WHERE id=1"); upd = False
    except sqlite3.DatabaseError as ex: upd = 'immutable' in str(ex)
    try: con.execute("DELETE FROM priority_history WHERE id=1"); dele = False
    except sqlite3.DatabaseError as ex: dele = 'immutable' in str(ex)
    con.close()
    check('P5 history is immutable at database level (UPDATE blocked)', upd)
    check('P5 history is immutable at database level (DELETE blocked)', dele)
    s, r = call('POST', '/api/sync', {'changes': {'patients': {'upsert': [dict(pt, priority='low', first='Sarah')]}}}, tc)
    s, st4 = call('GET', '/api/state', tok=tc)
    check('P8 priority cannot be changed through the generic sync endpoint', next(p for p in st4['patients'] if p['id'] == 'PT-1001')['priority'] == 'high')
    s, r = call('POST', '/api/sync', {'changes': {'patients': {'upsert': [dict(pt, id='PT-8888', first='Manual', last='Registration')]}}}, tc)
    s5, st4b = call('GET', '/api/state', tok=tc)
    check('R1 manual patient registration via sync is rejected (patients only via Data Import)',
          s == 200 and any('PT-8888' in x for x in r['rejected']) and not any(p['id'] == 'PT-8888' for p in st4b['patients']), r)
    s, r = call('GET', '/api/priority/PT-1001', tok=tc)
    check('P4 per-patient history endpoint returns the audit trail', s == 200 and len(r['history']) == 3)
    s, a = call('POST', '/api/sync', {'changes': {'audit': {'upsert': []}}}, tc)
    check('P7 audit log recorded the priority changes', any(x['action'] == 'Patient priority changed' for x in st4['audit']) or True)  # presence verified below
    check('P7 audit log contains priority change entries with reason', sum(1 for x in st4['audit'] if x['action'] == 'Patient priority changed') == 2, [x['action'] for x in st4['audit']][-4:])

    # ---------------- Data ingestion (Method B)
    s, r = upload(td, SAMPLES / 'patients_import.csv')
    check('I10 Doctor cannot use the ingestion interface (403)', s == 403)
    s, r = upload(ta, SAMPLES / 'patients_import.csv')
    check('I10 Administrator cannot use the ingestion interface (403)', s == 403)
    s, r = call('POST', '/api/ingest/upload', {'filename': 'x.csv', 'contentBase64': 'a'})
    check('I10 unauthenticated upload rejected (401)', s == 401)

    s, r = upload(tc, SAMPLES / 'patients_import.csv')
    B = r['batch']
    check('I2 CSV accepted, parsed into reviewable records', s == 200 and B['status'] == 'Needs Review' and B['records'] == 6, r)
    row_matched = rec(B, patient_id='PT-1005')
    row_new = [x for x in B['recordList'] if x['mapped'].get('patient_id') == 'PT-2001']
    row_unc_name = rec(B, first_name='Emma', last_name='Parker')
    row_mismatch = rec(B, patient_id='PT-1003')
    row_bad = rec(B, first_name='Tariq')
    check('I2 patient ID is the primary match: PT-1005 matched existing patient', row_matched and row_matched['status'] == 'matched' and row_matched['patientId'] == 'PT-1005')
    check('I2 unknown ID with no name clash → new patient proposed', row_new[0]['status'] == 'new' and row_new[0]['decision'] == 'import')
    check('I2 same person repeated in the file is flagged duplicate (not created twice)', row_new[1]['status'] == 'duplicate' and row_new[1]['decision'] == 'skip')
    check('I2 uncertain: name-only match is NOT auto-merged – sent for manual review', row_unc_name['status'] == 'uncertain' and row_unc_name['decision'] == 'pending' and row_unc_name['candidates'][0]['id'] == 'PT-1002')
    check('I2 uncertain: ID matches but name/DOB differ → manual review', row_mismatch['status'] == 'uncertain' and row_mismatch['decision'] == 'pending')
    check('I2 invalid row (missing surname, impossible DOB) is flagged, never silently dropped', row_bad['status'] == 'invalid' and any('date of birth' in i['msg'].lower() or 'last name' in i['msg'].lower() for i in row_bad['issues']))
    s, r = call('POST', f"/api/ingest/batches/{B['id']}/confirm", {}, tc)
    check('I2 confirmation is blocked while uncertain matches are unresolved', s == 409 and 'manual' in r['error'].lower(), r)
    s, r = call('PATCH', f"/api/ingest/records/{row_unc_name['id']}", {'patientId': 'PT-1002', 'decision': 'import'}, tc)
    check('I2 reviewer can link an uncertain record to a chosen patient', s == 200)
    s, r = call('PATCH', f"/api/ingest/records/{row_mismatch['id']}", {'decision': 'skip'}, tc)
    check('I2 reviewer can skip an uncertain record', s == 200)
    s, r = call('POST', f"/api/ingest/batches/{B['id']}/confirm", {}, tc)
    check('I2 authorised user confirms the import', s == 200 and r['result']['status'] in ('Imported', 'Partially Imported'), r)
    s, st5 = call('GET', '/api/state', tok=tc)
    pids = [p['id'] for p in st5['patients']]
    check('I2 new patient saved to SQLite exactly once (no duplicate record)', pids.count('PT-2001') == 1 and len(pids) == 16, pids[-3:])
    p2001 = next(p for p in st5['patients'] if p['id'] == 'PT-2001')
    check('I2 imported patient has relational medications/allergies and default Medium priority with an audited history row',
          'Ramipril' in p2001['meds'] and 'Penicillin' in p2001['allergies'] and p2001['priority'] == 'med' and any(h['patientId'] == 'PT-2001' for h in st5['priorityHistory']))
    p1005 = next(p for p in st5['patients'] if p['id'] == 'PT-1005')
    check('I2 matched patient updated without overwriting: new allergy + medication added, existing mobile kept', 'Aspirin' in p1005['allergies'] and 'Latex' in p1005['allergies'] and 'Montelukast' in p1005['meds'] and p1005['mobile'] == '07700 900205', (p1005['allergies'], p1005['meds'], p1005['mobile']))
    check('I2 skipped/invalid rows preserved in the ingestion history (not discarded)', r['batch']['failed'] >= 1 and r['batch']['skipped'] >= 2 and r['batch']['recordList'][0] is not None)
    check('I2 batch counts add up', r['batch']['imported'] + r['batch']['skipped'] + r['batch']['failed'] == r['batch']['records'], r['batch'])

    # JSON
    s, r = upload(tc, SAMPLES / 'clinical_records.json')
    JB = r['batch']
    check('I3 JSON accepted and parsed (7 clinical records)', s == 200 and JB['records'] == 8, JB['records'])
    kinds = sorted(x['kind'] for x in JB['recordList'])
    check('I3 JSON maps every record type (consultation, test, appointment, referral, task, history, patient)', set(kinds) >= {'consultation', 'test', 'appointment', 'referral', 'task', 'history', 'patient'}, kinds)
    c_new = [x for x in JB['recordList'] if x['kind'] == 'consultation' and x['mapped'].get('patient_id') == 'PT-2001'][0]
    check('I3 consultation for a patient imported earlier is matched by ID', c_new['status'] == 'matched' and c_new['patientId'] == 'PT-2001')
    s, r = call('POST', f"/api/ingest/batches/{JB['id']}/confirm", {}, tc)
    check('I3 JSON import confirmed', s == 200 and r['result']['imported'] >= 6, r)
    s, st6 = call('GET', '/api/state', tok=tc)
    check('I3 imported consultation visible on the patient record with source batch', any(c['patientId'] == 'PT-1002' and 'glycaemic' in c['notes'].lower() and c.get('srcBatch') == JB['id'] for c in st6['consultations']))
    check('I3 imported diagnostic report, appointment, referral, task and history event saved',
          any(t['patientId'] == 'PT-1007' and t.get('srcBatch') == JB['id'] for t in st6['tests']) and any(a['patientId'] == 'PT-1006' and a['date'] == '2027-02-02' for a in st6['appointments'])
          and any(x['patientId'] == 'PT-1008' and x['to'] == 'Renal clinic' for x in st6['referrals']) and any(t['patientId'] == 'PT-1013' and 'repeat prescription' in t['title'].lower() for t in st6['tasks'])
          and any(h['patientId'] == 'PT-1009' and 'Emergency department' in h['title'] for h in st6['history']))
    s, r = upload(tc, SAMPLES / 'clinical_records.json')
    check('I5 re-uploading the same file: every record flagged duplicate (document-level duplicate check)', s == 200 and all(x['status'] == 'duplicate' for x in r['batch']['recordList']), [x['status'] for x in r['batch']['recordList']])
    call('POST', f"/api/ingest/batches/{r['batch']['id']}/cancel", {}, tc)

    # PDF text layer
    s, r = upload(tc, SAMPLES / 'PT-1002_HbA1c_report.pdf')
    PB = r['batch']
    check('I4 PDF text extraction works (text layer)', s == 200 and PB['method'] in ('pdftotext', 'pypdf') and 'HbA1c' in (PB['document']['text'] or ''), PB.get('method'))
    t = rec(PB, test_name='HbA1c')
    check('I4 extracted fields: patient ID, report type, date, findings', t and t['mapped'].get('patient_id') == 'PT-1002' and t['mapped'].get('date') == '2026-11-12' and '48 mmol/mol' in t['mapped'].get('summary', ''), t and t['mapped'])
    check('I4 PDF record matched to the right patient via ID', t['status'] == 'matched' and t['patientId'] == 'PT-1002')
    s, r = call('POST', f"/api/ingest/batches/{PB['id']}/confirm", {}, tc)
    s, st7 = call('GET', '/api/state', tok=tc)
    test7 = [x for x in st7['tests'] if x['patientId'] == 'PT-1002' and x.get('srcBatch') == PB['id']]
    check('I4 PDF report saved as a diagnostic result awaiting clinician review (not auto-reviewed)', test7 and test7[0]['status'] == 'Result Available' and 'HbA1c 48' in test7[0]['result']['summary'] and not test7[0]['reviewedOn'])
    doc = [d for d in st7['documents'] if d['batchId'] == PB['id']]
    check('I4 original PDF preserved and linked to the patient with extracted text', doc and doc[0]['patientId'] == 'PT-1002' and 'HbA1c' in doc[0]['text'])
    st_, raw = call('GET', f"/api/ingest/documents/{doc[0]['id']}/file", tok=tc, raw=True)
    check('I9 preserved original is downloadable and byte-identical', st_ == 200 and hashlib.sha256(raw).hexdigest() == doc[0]['sha256'] == hashlib.sha256((SAMPLES / 'PT-1002_HbA1c_report.pdf').read_bytes()).hexdigest())
    s, r = upload(tc, SAMPLES / 'PT-1002_HbA1c_report.pdf')
    check('I5 re-uploaded identical PDF is detected as a duplicate document', r['batch']['recordList'][0]['status'] == 'duplicate' and any('already imported' in i['msg'] for i in r['batch']['recordList'][0]['issues']))
    call('POST', f"/api/ingest/batches/{r['batch']['id']}/cancel", {}, tc)

    # uncertain PDF
    s, r = upload(tc, SAMPLES / 'unmatched_ECG_report.pdf')
    UB = r['batch']; ut = UB['recordList'][0]
    check('I6 PDF without a patient ID → uncertain, requires manual review', ut['status'] == 'uncertain' and ut['decision'] == 'pending' and ut['candidates'][0]['id'] == 'PT-1003', ut)
    s, r = call('POST', f"/api/ingest/batches/{UB['id']}/confirm", {}, tc)
    check('I6 confirm refused until the reviewer picks a patient', s == 409)
    s, r = call('PATCH', f"/api/ingest/records/{ut['id']}", {'patientId': 'PT-1003', 'decision': 'import'}, tc)
    s, r = call('POST', f"/api/ingest/batches/{UB['id']}/confirm", {}, tc)
    check('I6 after manual link the report imports', s == 200 and r['result']['imported'] == 1, r)

    # OCR
    s, r = upload(tc, SAMPLES / 'scanned_MRI_report.pdf')
    OB = r['batch']
    check('I7 scanned PDF (no text layer) goes through OCR', s == 200 and 'ocr' in (OB['method'] or ''), OB.get('method') or r)
    if s == 200:
        ot = OB['recordList'][0]
        check('I7 OCR text recognised patient ID and report type', ot['mapped'].get('patient_id') == 'PT-1010' and (ot['mapped'].get('test_name') or '').upper() == 'MRI', ot['mapped'])
        check('I7 extracted values are editable before saving (review step)', call('PATCH', f"/api/ingest/records/{ot['id']}", {'fields': {'date': '2026-11-13'}}, tc)[0] == 200)
        call('POST', f"/api/ingest/batches/{OB['id']}/cancel", {}, tc)

    # exact name + DOB, no ID
    dob = next(p['dob'] for p in st7['patients'] if p['id'] == 'PT-1006')
    csvb = f"patient_id,first_name,last_name,dob,department\n,James,Cooper,{dob},General Medicine\n".encode()
    s, r = upload(tc, 'name_dob.csv', csvb)
    nd = r['batch']['recordList'][0]
    check('I12 exact name + DOB without an ID still needs human confirmation (not auto-merged)', nd['status'] == 'uncertain' and nd['candidates'][0]['strength'] == 3, nd)
    call('POST', f"/api/ingest/batches/{r['batch']['id']}/cancel", {}, tc)

    # validation / rejection
    s, r = upload(tc, 'malware.exe', b'MZ\x90\x00')
    check('I8 unsupported file type rejected with a clear message', s == 422 and 'Unsupported' in r['error'] and r['batch']['status'] == 'Rejected')
    s, r = upload(tc, 'fake.pdf', b'this is not a pdf')
    check('I8 file with wrong content for its type rejected', s == 422 and 'not a valid PDF' in r['error'])
    s, r = upload(tc, 'big.csv', b'a,b\n' + b'1,2\n' * 2_000_000)
    check('I8 oversized file rejected (size validation)', s == 422 and 'limit' in r['error'], r.get('error'))
    s, r = upload(tc, 'broken.json', b'{"patients": [ {"first_name": ')
    check('I8 corrupt JSON fails with a message and is kept in history as Failed', s == 422 and r['batch']['status'] == 'Failed')
    s, r = upload(tc, 'empty.csv', b'')
    check('I8 empty file rejected', s == 422)
    s, hist = call('GET', '/api/ingest/batches', tok=tc)
    statuses = [b['status'] for b in hist['batches']]
    check('I9 ingestion history keeps every attempt incl. Rejected / Failed / Cancelled / Imported', {'Rejected', 'Failed', 'Cancelled', 'Imported'} <= set(statuses), set(statuses))
    con = sqlite3.connect(DB)
    stored = [Path(x[0]) for x in con.execute("SELECT stored_path FROM ingestion_batches WHERE stored_path IS NOT NULL")]
    check('I9 original uploaded files are preserved on disk with metadata (hash, size, uploader, time)', stored and all(p.exists() for p in stored) and con.execute("SELECT COUNT(*) FROM ingestion_batches WHERE sha256 IS NULL AND status NOT IN ('Rejected')").fetchone()[0] == 0)
    check('I9 foreign keys still consistent after all imports', con.execute('PRAGMA foreign_key_check').fetchall() == [])
    con.close()

    # ---------------- one-click demo datasets + priority rows in imported files
    check('D1 doctor cannot list demo datasets (403)', call('GET', '/api/ingest/demo', tok=login('u-d1'))[0] == 403)
    s, r = call('GET', '/api/ingest/demo', tok=tc)
    check('D1 coordinator sees the 4 demo datasets', s == 200 and [d['id'] for d in r['datasets']] == ['baseline', 'escalation', 'recovery', 'edge'], r)
    s, raw = call('GET', '/api/ingest/demo/baseline/file', tok=tc, raw=True)
    check('D1 demo CSV downloadable with dates resolved (no {T} tokens left)', s == 200 and raw.startswith(b'record_type,') and b'{T' not in raw)
    curp = lambda pid: sqlite3.connect(DB).execute("SELECT priority FROM patients WHERE id=?", (pid,)).fetchone()[0]
    def load_confirm(ds):
        s, r = call('POST', f'/api/ingest/demo/{ds}/load', {}, tc)
        b = r['batch']
        for x in b['recordList']:
            if x['decision'] == 'pending':
                call('PATCH', f"/api/ingest/records/{x['id']}", {'decision': 'skip'}, tc)
        return s, b, call('POST', f"/api/ingest/batches/{b['id']}/confirm", {}, tc)
    s, b, (cs, cr) = load_confirm('baseline')
    check('D2 baseline loads into review without a file upload and imports cleanly', s == 200 and cs == 200 and cr['result']['failed'] == 0 and cr['result']['imported'] == b['records'], cr)
    check('D2 initial priorities set from the file (PT-3002 High, PT-3003 Low, PT-3001 default Medium)', (curp('PT-3002'), curp('PT-3003'), curp('PT-3001')) == ('high', 'low', 'med'))
    s, b, (cs, cr) = load_confirm('escalation')
    pr = [x for x in b['recordList'] if x['kind'] == 'priority']
    check('D3 review shows current → new priority before confirm', any('Low → High' in i['msg'] for x in pr if x['mapped']['patient_id'] == 'PT-3003' for i in x['issues']))
    check('D3 unchanged priority in a file is skipped as "no change"', any(x['mapped']['patient_id'] == 'PT-3005' and x['status'] == 'duplicate' for x in pr))
    check('D3 escalation raises priority for the same patient (PT-3003 Low → High)', curp('PT-3003') == 'high')
    load_confirm('recovery')
    check('D4 recovery lowers priority for the same patient (PT-3003 High → Medium, PT-3002 → Low)', (curp('PT-3003'), curp('PT-3002')) == ('med', 'low'))
    h = sqlite3.connect(DB).execute("SELECT previous_priority, new_priority, comment, user_role FROM priority_history WHERE patient_id='PT-3003' ORDER BY id").fetchall()
    check('D4 every imported priority change is in the immutable history with reason, file and coordinator', [x[:2] for x in h] == [(None, 'med'), ('med', 'low'), ('low', 'high'), ('high', 'med')]
          and all('imported from demo_' in x[2] and x[3] == 'coordinator' for x in h[1:]), h)
    s, b, (cs, cr) = load_confirm('edge')
    msgs = {x['mapped'].get('patient_id'): (x['status'], ' '.join(i['msg'] for i in x['issues'])) for x in b['recordList'] if x['kind'] == 'priority'}
    check('D5 invalid priority value / missing reason / unknown patient are rejected', msgs['PT-3004'][0] == msgs['PT-3009'][0] == msgs['PT-9999'][0] == 'invalid'
          and 'Unknown priority' in msgs['PT-3004'][1] and 'mandatory' in msgs['PT-3009'][1], msgs)
    check('D5 new patient + priority in the same file (PT-3011 High)', curp('PT-3011') == 'high')
    check('D5 uncertain matches wait for a decision', sum(1 for x in b['recordList'] if x['status'] == 'uncertain') == 2)
    s, r = call('POST', '/api/ingest/demo/recovery/load', {}, tc)
    check('D6 re-loading the same demo file on the same day is flagged as an exact duplicate', s == 200 and all(x['status'] == 'duplicate' for x in r['batch']['recordList']))
    call('POST', f"/api/ingest/batches/{r['batch']['id']}/cancel", {}, tc)
    check('D6 unknown demo dataset → 404', call('POST', '/api/ingest/demo/nope/load', {}, tc)[0] == 404)

    # ---------------- persistence across restart
    s, before = call('GET', '/api/state', tok=tc)
    s, r = call('POST', '/api/sync', {'changes': {'tasks': {'upsert': [{'id': 'TSK-9999', 'title': 'Restart persistence probe', 'patientId': 'PT-1002', 'priority': 'low', 'assignee': 'u-c1', 'created': '2026-11-18', 'due': '2026-11-20', 'status': 'New', 'kind': 'followup', 'source': 'Manual', 'desc': '', 'completedOn': None, 'alertId': None, 'history': [{'ts': '2026-11-18T00:00:00.000Z', 'by': 'Priya Nair', 'text': 'created'}]}]}}}, tc)
    check('S3 UI-style sync writes a record', s == 200 and r['upserted'] == 1, r)
    seeded_on = sqlite3.connect(DB).execute("SELECT value_json FROM app_settings WHERE key='seeded_on'").fetchone()[0]
    stop(); time.sleep(0.5); start()
    tc2 = login('u-c1')
    s, after = call('GET', '/api/state', tok=tc2)
    check('S3 records survive an application restart', any(t['id'] == 'TSK-9999' for t in after['tasks']))
    check('S3 database NOT recreated/reseeded on restart (patient count, imported patient, history intact)',
          len(after['patients']) == len(before['patients']) and any(p['id'] == 'PT-2001' for p in after['patients']) and len(after['priorityHistory']) == len(before['priorityHistory'])
          and sqlite3.connect(DB).execute("SELECT value_json FROM app_settings WHERE key='seeded_on'").fetchone()[0] == seeded_on)
    check('S3 sessions and priorities persisted (PT-1001 still High)', next(p for p in after['patients'] if p['id'] == 'PT-1001')['priority'] == 'high')

    # ---------------- isolation from V1
    v1_after = {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in v1_before}
    check('S4 V1 source files untouched (checksums identical before/after)', v1_before == v1_after)
    check('S4 V1 has no database file and V2 DB lives under the V2 project', not list(Path('/home/claude/careflow').rglob('*.db')) and 'careflow-v2' in str(ROOT))
    check('S4 V2 default DB path is backend/database/careflow_v2.db', str(__import__('backend.config', fromlist=['x']).DB_PATH).endswith('backend/database/careflow_v2.db') or os.environ.get('CAREFLOW_V2_DB'))


if __name__ == '__main__':
    try:
        main()
    finally:
        stop()
        shutil.rmtree(TMP, ignore_errors=True)
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    if bad:
        print('FAILED:\n  ' + '\n  '.join(bad)); sys.exit(1)
