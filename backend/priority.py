"""Auditable patient priority management (V2 decision #3).

Only the Care Coordinator and Doctor roles may change priority, always with a mandatory comment.
Every change appends an immutable row to priority_history (DB triggers block UPDATE/DELETE).
Neither the AI agent nor the care-gap engine calls this module – they only *suggest* in the UI.
"""
from . import db

LEVELS = ('high', 'med', 'low')
LABEL = {'high': 'High', 'med': 'Medium', 'low': 'Low'}
ALLOWED_ROLES = ('coordinator', 'doctor')
MIN_COMMENT = 5


class PriorityError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg); self.status = status


def can_change(conn, user, patient_id):
    if user['role'] not in ALLOWED_ROLES:
        return False
    if user['role'] == 'doctor':
        r = conn.execute("SELECT doctor_id FROM patients WHERE id=?", (patient_id,)).fetchone()
        return bool(r) and r['doctor_id'] == user['id']      # doctors act only on their own patients
    return True


def change_priority(conn, user, patient_id, new_priority, comment):
    if user['role'] not in ALLOWED_ROLES:
        raise PriorityError('Your role is not authorised to change patient priority', 403)
    if new_priority not in LEVELS:
        raise PriorityError('Priority must be High, Medium or Low')
    comment = (comment or '').strip()
    if len(comment) < MIN_COMMENT:
        raise PriorityError(f'A comment explaining the reason is mandatory (at least {MIN_COMMENT} characters)')
    with db.WRITE_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT id, priority, doctor_id FROM patients WHERE id=?", (patient_id,)).fetchone()
            if not row:
                raise PriorityError('Patient not found', 404)
            if user['role'] == 'doctor' and row['doctor_id'] != user['id']:
                raise PriorityError('Doctors can change priority only for their own patients', 403)
            old = row['priority']
            if old == new_priority:
                raise PriorityError('The new priority is the same as the current priority')
            ts = db.now_iso()
            conn.execute("UPDATE patients SET priority=?, priority_updated_at=? WHERE id=?", (new_priority, ts, patient_id))
            cur = conn.execute("INSERT INTO priority_history(patient_id,previous_priority,new_priority,comment,user_id,user_name,user_role,changed_at) VALUES(?,?,?,?,?,?,?,?)",
                               (patient_id, old, new_priority, comment, user['id'], user['name'], user['role'], ts))
            aid = db.next_id(conn, 'AUD')
            conn.execute("INSERT INTO audit_log(id,ts,user_id,user_name,role,action,patient_id,entity,detail) VALUES(?,?,?,?,?,?,?,?,?)",
                         (aid, ts, user['id'], user['name'], user['role'], 'Patient priority changed', patient_id, f'PRI-{cur.lastrowid}',
                          f'{LABEL[old]} → {LABEL[new_priority]}: {comment}'))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK"); raise
    return {'id': cur.lastrowid, 'patientId': patient_id, 'previous': old, 'new': new_priority, 'comment': comment,
            'userId': user['id'], 'user': user['name'], 'role': user['role'], 'at': ts}
