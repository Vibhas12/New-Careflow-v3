"""Mapping between the relational SQLite schema and the application state shape used by the UI.

load_state(conn)            -> dict (collections the UI works with)
apply_changes(conn, ch, u)  -> upserts / deletes sent by the UI, inside ONE transaction

Rules enforced here (server side, not just in the UI):
  * patients.priority is never written from a client change – only via priority.change_priority().
  * priority_history, documents and ingestion_* are server-owned: the UI cannot sync them.
  * patients are never deleted through sync.
  * patients are never CREATED through sync by a user – manual registration was removed; new patients
    enter only through Data Import (ingest.py) or the seed loader (system actor).
"""
import json
from . import db

# (js_key, column, kind)  kind: None | 'bool'
def C(js, col=None, kind=None):
    return (js, col or js, kind)

SPECS = {
 'users': dict(table='users', cols=[C('id'), C('name'), C('role'), C('title'), C('email'), C('phone'), C('active', None, 'bool')]),
 'patients': dict(table='patients', cols=[
    C('id'), C('first', 'first_name'), C('last', 'last_name'), C('dob'), C('gender'), C('email'), C('mobile'), C('address'),
    C('ecName', 'ec_name'), C('ecPhone', 'ec_phone'), C('department'), C('primary', 'primary_condition'),
    C('secondary', 'secondary_conditions'), C('prevSurg', 'previous_surgeries'), C('famHist', 'family_history'),
    C('insProvider', 'ins_provider'), C('policy'), C('coverage'), C('doctorId', 'doctor_id'), C('coordId', 'coord_id'),
    C('registeredOn', 'registered_on'), C('reviewDue', 'review_due'), C('planReviewDue', 'plan_review_due'),
    C('discharged', None, 'bool'), C('draft', None, 'bool'),
    C('priority', None), C('priorityUpdatedAt', 'priority_updated_at'), C('srcBatch', 'source_batch_id')],
    ro={'priority', 'priority_updated_at', 'source_batch_id'}),
 'appointments': dict(table='appointments', cols=[
    C('id'), C('patientId', 'patient_id'), C('doctorId', 'doctor_id'), C('dept'), C('date', 'appt_date'), C('time', 'appt_time'),
    C('type'), C('status'), C('createdOn', 'created_on'), C('notes'), C('srcBatch', 'source_batch_id')], ro={'source_batch_id'}),
 'tests': dict(table='diagnostic_tests', cols=[
    C('id'), C('patientId', 'patient_id'), C('name'), C('orderedBy', 'ordered_by'), C('orderedOn', 'ordered_on'),
    C('scheduledDate', 'scheduled_date'), C('status'), C('completedOn', 'completed_on'), C('resultOn', 'result_on'),
    C('reviewedOn', 'reviewed_on'), C('reviewedBy', 'reviewed_by'), C('reviewNote', 'review_note'), C('abnormal', None, 'bool'),
    C('priority'), C('notes'), C('documentId', 'document_id'), C('srcBatch', 'source_batch_id')], ro={'source_batch_id', 'document_id'}),
 'referrals': dict(table='referrals', cols=[
    C('id'), C('patientId', 'patient_id'), C('to', 'referred_to'), C('reason'), C('status'), C('createdOn', 'created_on'),
    C('by', 'referred_by'), C('srcBatch', 'source_batch_id')], ro={'source_batch_id'}),
 'prescriptions': dict(table='prescriptions', cols=[
    C('id'), C('patientId', 'patient_id'), C('drug'), C('prescribedBy', 'prescribed_by'), C('date', 'rx_date'),
    C('refillDue', 'refill_due'), C('status'), C('srcBatch', 'source_batch_id')], ro={'source_batch_id'}),
 'consultations': dict(table='consultations', cols=[
    C('id'), C('patientId', 'patient_id'), C('doctorId', 'doctor_id'), C('date', 'consult_date'), C('notes'), C('diagnosis'),
    C('prescription'), C('plan'), C('followUp', 'follow_up'), C('instructions'), C('createdOn', 'created_on'),
    C('srcBatch', 'source_batch_id')], ro={'source_batch_id'}),
 'tasks': dict(table='tasks', cols=[
    C('id'), C('title'), C('patientId', 'patient_id'), C('priority'), C('assignee'), C('created'), C('due'), C('status'),
    C('kind'), C('source'), C('desc', 'description'), C('completedOn', 'completed_on'), C('alertId', 'alert_id'),
    C('srcBatch', 'source_batch_id')], ro={'source_batch_id'}),
 'reminders': dict(table='reminders', cols=[
    C('id'), C('kind'), C('refId', 'ref_id'), C('patientId', 'patient_id'), C('offset', 'offset_label'), C('channel'),
    C('scheduledFor', 'scheduled_for'), C('status'), C('sentAt', 'sent_at'), C('label'), C('message'), C('simulated', None, 'bool')]),
 'comms': dict(table='communications', cols=[
    C('id'), C('ts'), C('direction'), C('category'), C('recipient'), C('patientId', 'patient_id'), C('message'), C('channel'),
    C('status'), C('sender'), C('simulated', None, 'bool')]),
 'notifications': dict(table='notifications', cols=[
    C('id'), C('ts'), C('toUser', 'to_user'), C('toRole', 'to_role'), C('title'), C('text'), C('route'),
    C('patientId', 'patient_id'), C('read', 'is_read', 'bool'), C('level')]),
 'feedback': dict(table='feedback', cols=[
    C('id'), C('patientId', 'patient_id'), C('doctorId', 'doctor_id'), C('dept'), C('rating'), C('recommend'),
    C('comment'), C('date', 'fb_date'), C('demo', None, 'bool')]),
 'history': dict(table='medical_history', extra=False, cols=[
    C('id'), C('patientId', 'patient_id'), C('date', 'event_date'), C('type'), C('title'), C('detail'), C('srcBatch', 'source_batch_id')],
    ro={'source_batch_id'}),
 'audit': dict(table='audit_log', cols=[
    C('id'), C('ts'), C('userId', 'user_id'), C('user', 'user_name'), C('role'), C('action'), C('patientId', 'patient_id'),
    C('entity'), C('detail')]),
}
# upsert order respects foreign keys; deletes run in reverse
ORDER = ['users', 'patients', 'appointments', 'tests', 'referrals', 'prescriptions', 'consultations', 'tasks',
         'reminders', 'comms', 'notifications', 'feedback', 'history', 'audit']
NO_DELETE = {'users', 'patients', 'audit', 'history', 'consultations', 'prescriptions', 'tests', 'feedback'}
# blob-style collections (JSON in a relational wrapper)
BLOBS = {
 'alertState': dict(table='alert_state', keyed=True, pat=lambda o: (o.get('snap') or {}).get('patientId'), status=lambda o: o.get('status')),
 'proposals': dict(table='ai_proposals', keyed=False, pat=lambda o: o.get('patientId')),
 'chat': dict(table='chat_messages', keyed=False, pat=None),
 'aiMeta': dict(table='ai_meta', keyed=True, pat=None, pk='patient_id'),
}
WRITE_ROLES = {   # which roles may write which collections (prototype-grade server RBAC)
 'patients': {'coordinator', 'doctor'}, 'consultations': {'doctor'}, 'prescriptions': {'doctor'},
 'tests': {'coordinator', 'doctor'}, 'referrals': {'doctor', 'coordinator'}, 'history': {'coordinator', 'doctor'},
 'users': {'admin'}, 'feedback': {'coordinator', 'doctor', 'admin'},
}
EMPTY_LIST_DEFAULTS = {'allergies': 'None recorded', 'meds': 'None', 'prevDx': 'None'}
NONE_WORDS = {'', 'none', 'none recorded', 'n/a', 'nil', 'not recorded'}


def split_list(s):
    if s is None:
        return []
    out = []
    for part in str(s).split(';'):
        p = part.strip()
        if p and p.lower() not in NONE_WORDS:
            out.append(p)
    return out


def _conv_out(kind, v):
    if kind == 'bool':
        return bool(v)
    return v


def _conv_in(kind, v):
    if kind == 'bool':
        return 1 if v else 0
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return v


def row_obj(spec, row):
    obj = {}
    for js, col, kind in spec['cols']:
        v = row[col]
        if js in ('srcBatch', 'priorityUpdatedAt') and v is None:
            continue
        obj[js] = _conv_out(kind, v)
    if spec.get('extra', True) and 'extra_json' in row.keys() and row['extra_json']:
        obj.update(json.loads(row['extra_json']))
    return obj


# ------------------------------------------------------------------ load
def load_state(conn):
    S = {}
    for coll in ORDER:
        spec = SPECS[coll]
        # the UI treats DB.audit as newest-first (audit() unshifts; dashboards use slice(0,n) as "latest"),
        # so server-written rows such as import entries must come back in the same order
        order = 'ORDER BY ts DESC, rowid DESC' if coll == 'audit' else 'ORDER BY rowid'
        rows = conn.execute(f"SELECT * FROM {spec['table']} {order}").fetchall()
        S[coll] = [row_obj(spec, r) for r in rows]
    # users: departments
    deps = {}
    for r in conn.execute("SELECT user_id, department FROM user_departments ORDER BY rowid"):
        deps.setdefault(r[0], []).append(r[1])
    for u in S['users']:
        u['depts'] = deps.get(u['id'], [])
    # patients: child tables
    al, md, dx, cp = {}, {}, {}, {}
    for r in conn.execute("SELECT patient_id, substance FROM allergies ORDER BY id"):
        al.setdefault(r[0], []).append(r[1])
    for r in conn.execute("SELECT patient_id, description FROM medications WHERE status='Active' ORDER BY id"):
        md.setdefault(r[0], []).append(r[1])
    for r in conn.execute("SELECT patient_id, description FROM diagnoses ORDER BY id"):
        dx.setdefault(r[0], []).append(r[1])
    for r in conn.execute("SELECT patient_id, plan_text, start_date FROM care_plans"):
        cp[r[0]] = (r[1], r[2])
    prow = {r['id']: r for r in conn.execute("SELECT id, outcome_status, outcome_note, outcome_date, outcome_by FROM patients")}
    for p in S['patients']:
        pid = p['id']
        p['allergies'] = '; '.join(al.get(pid, [])) or EMPTY_LIST_DEFAULTS['allergies']
        p['meds'] = '; '.join(md.get(pid, [])) or EMPTY_LIST_DEFAULTS['meds']
        p['prevDx'] = '; '.join(dx.get(pid, [])) or EMPTY_LIST_DEFAULTS['prevDx']
        p['treatmentPlan'], p['treatmentStart'] = cp.get(pid, ('', None))
        o = prow[pid]
        p['outcome'] = ({'status': o['outcome_status'], 'note': o['outcome_note'], 'date': o['outcome_date'], 'by': o['outcome_by']}
                        if o['outcome_status'] else None)
    # tests: result + values
    vals = {}
    for r in conn.execute("SELECT * FROM test_result_values ORDER BY test_id, seq"):
        vals.setdefault(r['test_id'], []).append({'k': r['analyte'], 'v': _num(r['value']), 'u': r['unit'], 'ref': r['ref_range'], 'flag': r['flag'] or ''})
    trow = {r['id']: r for r in conn.execute("SELECT id, result_summary, result_source FROM diagnostic_tests")}
    for t in S['tests']:
        r = trow[t['id']]
        t['result'] = ({'summary': r['result_summary'], 'values': vals.get(t['id'], []), 'source': r['result_source']}
                       if (r['result_summary'] is not None or r['result_source'] is not None or vals.get(t['id'])) else None)
    # tasks: events
    ev = {}
    for r in conn.execute("SELECT * FROM task_events ORDER BY task_id, seq"):
        ev.setdefault(r['task_id'], []).append({'ts': r['ts'], 'by': r['by_name'], 'text': r['text']})
    for k in S['tasks']:
        k['history'] = ev.get(k['id'], [])
    # blobs
    for name, b in BLOBS.items():
        rows = conn.execute(f"SELECT * FROM {b['table']} ORDER BY rowid").fetchall()
        if b['keyed']:
            pk = b.get('pk', 'id')
            S[name] = {r[pk]: json.loads(r['data_json']) for r in rows}
        else:
            S[name] = [json.loads(r['data_json']) for r in rows]
    S['seq'] = {r[0]: r[1] for r in conn.execute("SELECT prefix, value FROM id_sequences")}
    r = conn.execute("SELECT value_json FROM app_settings WHERE key='settings'").fetchone()
    S['settings'] = json.loads(r[0]) if r else {}
    # server-owned collections (read-only for the UI)
    S['priorityHistory'] = [{'id': r['id'], 'patientId': r['patient_id'], 'previous': r['previous_priority'], 'new': r['new_priority'],
                             'comment': r['comment'], 'userId': r['user_id'], 'user': r['user_name'], 'role': r['user_role'], 'at': r['changed_at']}
                            for r in conn.execute("SELECT * FROM priority_history ORDER BY id")]
    S['documents'] = [{'id': r['id'], 'batchId': r['batch_id'], 'patientId': r['patient_id'], 'filename': r['filename'], 'type': r['file_type'],
                       'size': r['size_bytes'], 'sha256': r['sha256'], 'docType': r['doc_type'], 'method': r['extraction_method'],
                       'text': (r['extracted_text'] or '')[:6000], 'uploadedAt': r['uploaded_at'], 'uploadedBy': r['uploaded_by']}
                      for r in conn.execute("SELECT * FROM documents ORDER BY uploaded_at")]
    return S


def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() and '.' not in str(v) else f
    except (TypeError, ValueError):
        return v


# ------------------------------------------------------------------ write
def _split_known(spec, obj):
    known = {js for js, _, _ in spec['cols']}
    hooked = {'depts', 'allergies', 'meds', 'prevDx', 'treatmentPlan', 'treatmentStart', 'outcome', 'result', 'history', 'srcBatch', 'priority', 'priorityUpdatedAt'}
    extra = {k: v for k, v in obj.items() if k not in known and k not in hooked}
    return extra


def _upsert(conn, coll, obj, actor, report, ctx=None):
    ctx = ctx or {}
    spec = SPECS[coll]
    table = spec['table']
    ro = spec.get('ro', set())
    cols = [(js, col, kind) for js, col, kind in spec['cols']]
    has_extra = spec.get('extra', True)
    exists = conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (obj['id'],)).fetchone() is not None
    names, vals = [], []
    for js, col, kind in cols:
        if col in ro:
            continue
        names.append(col)
        vals.append(_conv_in(kind, obj.get(js)))
    if has_extra:
        names.append('extra_json'); vals.append(json.dumps(_split_known(spec, obj)))
    if coll == 'users' and not exists:
        names.append('password_hash'); vals.append(db.hash_password(__import__('backend.config', fromlist=['x']).DEMO_PASSWORD))
    if coll == 'patients' and not exists:
        names += ['priority', 'priority_updated_at']; vals += [ctx.get('initial_priority', {}).get(obj['id'], 'med'), db.now_iso()]
    ph = ','.join('?' * len(names))
    upd = ','.join(f"{n}=excluded.{n}" for n in names if n != 'id')
    conn.execute(f"INSERT INTO {table}({','.join(names)}) VALUES({ph}) ON CONFLICT(id) DO UPDATE SET {upd}", vals)
    # hooks
    if coll == 'users':
        conn.execute("DELETE FROM user_departments WHERE user_id=?", (obj['id'],))
        for d in obj.get('depts') or []:
            conn.execute("INSERT OR IGNORE INTO departments(name) VALUES(?)", (d,))
            conn.execute("INSERT OR IGNORE INTO user_departments VALUES(?,?)", (obj['id'], d))
    elif coll == 'patients':
        pid = obj['id']
        if not exists:   # initial priority is audited too (never a silent default)
            conn.execute("INSERT INTO priority_history(patient_id,previous_priority,new_priority,comment,user_id,user_name,user_role,changed_at) VALUES(?,?,?,?,?,?,?,?)",
                         (pid, None, ctx.get('initial_priority', {}).get(pid, 'med'), ctx.get('initial_comment', 'Default priority assigned when the patient record was created'),
                          actor.get('id'), actor.get('name', 'System'), actor.get('role', 'system'), db.now_iso()))
        _replace_list(conn, 'allergies', 'substance', pid, split_list(obj.get('allergies')))
        _replace_list(conn, 'medications', 'description', pid, split_list(obj.get('meds')), extra_cols={'status': 'Active'})
        _replace_list(conn, 'diagnoses', 'description', pid, split_list(obj.get('prevDx')))
        if obj.get('treatmentPlan') is not None or obj.get('treatmentStart') is not None:
            conn.execute("INSERT INTO care_plans(patient_id,plan_text,start_date) VALUES(?,?,?) ON CONFLICT(patient_id) DO UPDATE SET plan_text=excluded.plan_text, start_date=excluded.start_date",
                         (pid, obj.get('treatmentPlan'), obj.get('treatmentStart')))
        o = obj.get('outcome')
        conn.execute("UPDATE patients SET outcome_status=?,outcome_note=?,outcome_date=?,outcome_by=? WHERE id=?",
                     ((o or {}).get('status'), (o or {}).get('note'), (o or {}).get('date'), (o or {}).get('by'), pid))
    elif coll == 'tests':
        r = obj.get('result')
        conn.execute("UPDATE diagnostic_tests SET result_summary=?, result_source=? WHERE id=?",
                     ((r or {}).get('summary'), (r or {}).get('source'), obj['id']))
        conn.execute("DELETE FROM test_result_values WHERE test_id=?", (obj['id'],))
        for i, v in enumerate((r or {}).get('values') or []):
            conn.execute("INSERT INTO test_result_values(test_id,seq,analyte,value,unit,ref_range,flag) VALUES(?,?,?,?,?,?,?)",
                         (obj['id'], i, v.get('k'), None if v.get('v') is None else str(v.get('v')), v.get('u'), v.get('ref'), v.get('flag')))
    elif coll == 'tasks':
        conn.execute("DELETE FROM task_events WHERE task_id=?", (obj['id'],))
        for i, h in enumerate(obj.get('history') or []):
            conn.execute("INSERT INTO task_events(task_id,seq,ts,by_name,text) VALUES(?,?,?,?,?)", (obj['id'], i, h.get('ts'), h.get('by'), h.get('text')))
    report['upserted'] = report.get('upserted', 0) + 1


def _replace_list(conn, table, col, pid, items, extra_cols=None):
    cur = [r[0] for r in conn.execute(f"SELECT {col} FROM {table} WHERE patient_id=?", (pid,))]
    if cur == items:
        return
    conn.execute(f"DELETE FROM {table} WHERE patient_id=?", (pid,))
    for it in items:
        names = ['patient_id', col] + list((extra_cols or {}).keys())
        conn.execute(f"INSERT OR IGNORE INTO {table}({','.join(names)}) VALUES({','.join('?'*len(names))})", [pid, it] + list((extra_cols or {}).values()))


def apply_changes(conn, changes, actor, ctx=None):
    """changes = {coll: {'upsert': [obj...], 'delete': [id...]}, 'blobs': {...}, 'seq': {...}, 'settings': {...}}"""
    report = {'upserted': 0, 'deleted': 0, 'rejected': []}
    role = actor.get('role')
    with db.WRITE_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for coll in ORDER:
                ch = changes.get(coll)
                if not ch:
                    continue
                allowed = WRITE_ROLES.get(coll)
                if allowed and role != 'system' and role not in allowed and (ch.get('upsert') or ch.get('delete')):
                    report['rejected'].append(f"{coll}: role '{role}' may not write this collection")
                    continue
                for obj in ch.get('upsert') or []:
                    if not obj.get('id'):
                        continue
                    if coll == 'patients' and role != 'system' and not conn.execute("SELECT 1 FROM patients WHERE id=?", (obj['id'],)).fetchone():
                        report['rejected'].append(f"patients: creating {obj['id']} is not permitted – new patients are added through Data Import")
                        continue
                    _upsert(conn, coll, obj, actor, report, ctx)
            for coll in reversed(ORDER):
                ch = changes.get(coll)
                if not ch:
                    continue
                for _id in ch.get('delete') or []:
                    if coll in NO_DELETE:
                        report['rejected'].append(f"{coll}: delete of {_id} not permitted")
                        continue
                    conn.execute(f"DELETE FROM {SPECS[coll]['table']} WHERE id=?", (_id,))
                    report['deleted'] += 1
            for name, ch in (changes.get('blobs') or {}).items():
                b = BLOBS[name]
                pk = b.get('pk', 'id')
                for key, obj in (ch.get('upsert') or {}).items():
                    cols, vals = [pk], [key]
                    if b.get('pat'):
                        pid = b['pat'](obj)
                        ok = pid and conn.execute("SELECT 1 FROM patients WHERE id=?", (pid,)).fetchone()
                        cols.append('patient_id'); vals.append(pid if ok else None)
                        if name == 'alertState':
                            cols.append('status'); vals.append(b['status'](obj))
                    elif name == 'proposals':
                        pass
                    cols.append('data_json'); vals.append(json.dumps(obj))
                    upd = ','.join(f"{c}=excluded.{c}" for c in cols if c != pk)
                    conn.execute(f"INSERT INTO {b['table']}({','.join(cols)}) VALUES({','.join('?'*len(cols))}) ON CONFLICT({pk}) DO UPDATE SET {upd}", vals)
                for key in ch.get('delete') or []:
                    conn.execute(f"DELETE FROM {b['table']} WHERE {pk}=?", (key,))
            for prefix, val in (changes.get('seq') or {}).items():
                conn.execute("INSERT INTO id_sequences(prefix,value) VALUES(?,?) ON CONFLICT(prefix) DO UPDATE SET value=MAX(value,excluded.value)", (prefix, int(val)))
            if 'settings' in changes and changes['settings'] is not None:
                conn.execute("INSERT INTO app_settings(key,value_json) VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (json.dumps(changes['settings']),))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return report
