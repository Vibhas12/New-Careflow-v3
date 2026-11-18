"""Phase 2: appointments, diagnostic tests, tasks, referrals, consultations, notifications."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Appointment, Notification, Patient, Reminder, Task

FUTURE = (date.today() + timedelta(days=12)).isoformat()


def own_patient(doctor) -> dict:
    return doctor.get('/api/patients', params={'pageSize': 1, 'sort': 'id'}).json()['items'][0]


def other_patient(coord) -> dict:
    return next(p for p in coord.get('/api/patients', params={'pageSize': 100, 'sort': 'id'}).json()['items'] if p['doctorId'] != 'u-d1')


def book(client, pid, time='10:00', d=FUTURE, doctor='u-d1', **kw):
    return client.post('/api/appointments', json={'patientId': pid, 'doctorId': doctor, 'date': d, 'time': time, 'type': 'Follow-up review', **kw})


# ---------------------------------------------------------------- appointments
def test_book_creates_reminders_and_notifies_doctor(coord, doctor):
    pid = own_patient(doctor)['id']
    r = book(coord, pid, '08:30')
    assert r.status_code == 201, r.text
    a = r.json()
    assert a['status'] == 'Scheduled' and a['patientName'] and a['doctorName'] == 'Dr. Sarah Wilson'
    with SessionLocal() as db:
        assert db.execute(select(Reminder).where(Reminder.ref_id == a['id'], Reminder.status == 'Scheduled')).first()
    notes = doctor.get('/api/notifications').json()
    assert notes['unread'] >= 1 and any(n['title'] == 'Appointment booked' for n in notes['items'])


def test_double_booking_is_rejected(coord, doctor):
    pid = own_patient(doctor)['id']
    assert book(coord, pid, '09:00').status_code == 201
    r = book(coord, pid, '09:00')
    assert r.status_code == 409 and 'already booked' in r.json()['detail']
    assert '09:00' not in coord.get('/api/appointments/slots', params={'doctorId': 'u-d1', 'date': FUTURE}).json()['slots']


@pytest.mark.parametrize('kw,code', [({'time': '08:15'}, 422), ({'d': '2020-01-01'}, 422), ({'doctor': 'u-c1'}, 422)])
def test_booking_validation(coord, doctor, kw, code):
    assert book(coord, own_patient(doctor)['id'], **kw).status_code == code


def test_unknown_type_and_admin_cannot_book(coord, admin, doctor):
    pid = own_patient(doctor)['id']
    assert coord.post('/api/appointments', json={'patientId': pid, 'doctorId': 'u-d1', 'date': FUTURE, 'time': '11:00', 'type': 'Spa day'}).status_code == 422
    assert book(admin, pid, '11:30').status_code == 403
    assert admin.get('/api/appointments').status_code == 200          # admins see the diary for scheduling


def test_doctor_sees_only_own_diary(doctor):
    items = doctor.get('/api/appointments').json()['items']
    with SessionLocal() as db:
        own = set(db.execute(select(Patient.id).where(Patient.doctor_id == 'u-d1')).scalars())
    assert items and all(a['doctorId'] == 'u-d1' or a['patientId'] in own for a in items)


def test_confirm_reschedule_cancel_flow(coord, doctor):
    a = book(coord, own_patient(doctor)['id'], '13:00').json()
    assert coord.post(f"/api/appointments/{a['id']}/confirm").json()['status'] == 'Confirmed'
    assert coord.post(f"/api/appointments/{a['id']}/confirm").status_code == 409
    assert coord.post(f"/api/appointments/{a['id']}/complete").status_code == 409             # future appointment
    r = coord.post(f"/api/appointments/{a['id']}/reschedule", json={'date': FUTURE, 'time': '13:30', 'reason': 'Patient request'})
    assert r.status_code == 200 and r.json()['apptTime'] == '13:30' and r.json()['status'] == 'Scheduled' and 'Rescheduled from' in r.json()['notes']
    assert coord.post(f"/api/appointments/{a['id']}/cancel", json={'reason': ''}).status_code == 422
    assert coord.post(f"/api/appointments/{a['id']}/cancel", json={'reason': 'Patient unwell'}).json()['status'] == 'Cancelled'
    assert coord.post(f"/api/appointments/{a['id']}/reschedule", json={'date': FUTURE, 'time': '14:00'}).status_code == 409
    with SessionLocal() as db:
        assert not db.execute(select(Reminder).where(Reminder.ref_id == a['id'], Reminder.status == 'Scheduled')).first()


def test_cancelled_slot_can_be_rebooked(coord, doctor):
    pid = own_patient(doctor)['id']
    a = book(coord, pid, '15:00').json()
    coord.post(f"/api/appointments/{a['id']}/cancel", json={'reason': 'Clinic closed'})
    assert book(coord, pid, '15:00').status_code == 201


def test_mark_missed_notifies_and_logs(coord, doctor):
    pid = own_patient(doctor)['id']
    with SessionLocal() as db:                       # an appointment from yesterday that nobody closed
        db.add(Appointment(id='APT-T1', patient_id=pid, doctor_id='u-d1', appt_date=date.today() - timedelta(days=1), appt_time='10:00',
                           type='Consultation', status='Scheduled'))
        db.commit()
    assert coord.post('/api/appointments/APT-T1/miss').json()['status'] == 'Missed'
    assert any(n['title'] == 'Patient missed appointment' and n['level'] == 'high' for n in doctor.get('/api/notifications').json()['items'])


def test_doctor_cannot_act_on_other_doctors_appointment(coord, doctor):
    other = other_patient(coord)
    a = book(coord, other['id'], '10:30', doctor=other['doctorId']).json()
    assert doctor.post(f"/api/appointments/{a['id']}/confirm").status_code == 404


# ---------------------------------------------------------------- diagnostic tests
def test_full_test_workflow(coord, doctor):
    p = own_patient(doctor)
    r = doctor.post('/api/tests', json={'patientId': p['id'], 'name': 'HbA1c', 'priority': 'Urgent', 'notes': 'Fasting'})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t['status'] == 'Ordered' and t['orderedByName'] == 'Dr. Sarah Wilson'
    with SessionLocal() as db:
        task = db.execute(select(Task).where(Task.test_id == t['id'])).scalar_one()
        assert task.priority == 'high' and task.status == 'New' and task.kind == 'test'
    assert doctor.post(f"/api/tests/{t['id']}/schedule", json={'date': FUTURE}).status_code == 403
    assert coord.post(f"/api/tests/{t['id']}/schedule", json={'date': '2020-01-01'}).status_code == 422
    assert coord.post(f"/api/tests/{t['id']}/schedule", json={'date': FUTURE}).json()['status'] == 'Scheduled'
    with SessionLocal() as db:
        assert db.get(Task, task.id).status == 'Completed'                                 # scheduling task closed
    assert coord.post(f"/api/tests/{t['id']}/result", json={'abnormal': True}).status_code == 409   # not completed yet
    assert coord.post(f"/api/tests/{t['id']}/complete").json()['status'] == 'Completed'
    res = coord.post(f"/api/tests/{t['id']}/result", json={'abnormal': True}).json()
    assert res['status'] == 'Result Available' and res['abnormal'] and any(v['flag'] for v in res['values'])
    assert any(n['title'] == 'Abnormal result flagged for review' for n in doctor.get('/api/notifications').json()['items'])
    assert t['id'] in [x['id'] for x in doctor.get('/api/tests', params={'stage': 'review'}).json()]
    assert coord.post(f"/api/tests/{t['id']}/review", json={'note': 'x'}).status_code == 403
    rv = doctor.post(f"/api/tests/{t['id']}/review", json={'note': 'Start metformin; repeat in 3 months'}).json()
    assert rv['status'] == 'Reviewed' and rv['reviewNote'].startswith('Start metformin')
    assert doctor.post(f"/api/tests/{t['id']}/review", json={}).status_code == 409


def test_test_request_permissions(coord, doctor, admin):
    assert coord.post('/api/tests', json={'patientId': own_patient(doctor)['id'], 'name': 'ECG'}).status_code == 403
    assert doctor.post('/api/tests', json={'patientId': other_patient(coord)['id'], 'name': 'ECG'}).status_code == 404
    assert doctor.post('/api/tests', json={'patientId': own_patient(doctor)['id'], 'name': 'Tarot'}).status_code == 422
    assert admin.get('/api/tests').status_code == 403


# ---------------------------------------------------------------- tasks
def test_task_create_reassign_complete(coord, doctor):
    pid = own_patient(doctor)['id']
    r = coord.post('/api/tasks', json={'title': 'Call patient about diet plan', 'patientId': pid, 'assignee': 'u-c1', 'due': FUTURE})
    assert r.status_code == 201
    t = r.json()
    r = coord.patch(f"/api/tasks/{t['id']}", json={'assignee': 'u-d1', 'status': 'In Progress', 'note': 'Needs doctor input'})
    body = r.json()
    assert body['assigneeName'] == 'Dr. Sarah Wilson' and body['status'] == 'In Progress' and len(body['events']) == 2
    assert 'Reassigned' in body['events'][-1]['text'] and 'Note: Needs doctor input' in body['events'][-1]['text']
    assert any(n['title'] == 'Task reassigned to you' for n in doctor.get('/api/notifications').json()['items'])
    done = doctor.patch(f"/api/tasks/{t['id']}", json={'status': 'Completed'}).json()
    assert done['completedOn'] == date.today().isoformat()
    assert doctor.patch(f"/api/tasks/{t['id']}", json={'status': 'Completed'}).status_code == 409   # nothing changed


def test_task_visibility_and_validation(coord, doctor):
    other = other_patient(coord)
    t = coord.post('/api/tasks', json={'title': 'Chase referral letter', 'patientId': other['id'], 'assignee': 'u-c1', 'due': FUTURE}).json()
    assert doctor.patch(f"/api/tasks/{t['id']}", json={'status': 'Completed'}).status_code == 404
    assert t['id'] not in [x['id'] for x in doctor.get('/api/tasks').json()]
    assert coord.post('/api/tasks', json={'title': 'x', 'assignee': 'u-c1', 'due': FUTURE}).status_code == 422          # title too short
    assert coord.post('/api/tasks', json={'title': 'Valid title', 'assignee': 'nobody', 'due': FUTURE}).status_code == 422
    assert coord.get('/api/tasks', params={'assignee': 'me', 'includeCompleted': 'false'}).status_code == 200


# ---------------------------------------------------------------- referrals & consultations
def test_referral_lifecycle(coord, doctor):
    pid = own_patient(doctor)['id']
    r = coord.post(f'/api/patients/{pid}/referrals', json={'referredTo': 'Dietitian', 'reason': 'Weight management programme'})
    assert r.status_code == 201 and r.json()['status'] == 'Pending'
    rid = r.json()['id']
    assert coord.post(f'/api/referrals/{rid}/status', json={'status': 'Completed'}).status_code == 409   # must be booked first
    assert coord.post(f'/api/referrals/{rid}/status', json={'status': 'Booked'}).json()['status'] == 'Booked'
    assert doctor.post(f'/api/referrals/{rid}/status', json={'status': 'Completed'}).json()['status'] == 'Completed'
    assert coord.post(f'/api/referrals/{rid}/status', json={'status': 'Booked'}).status_code == 409


def test_consultation_updates_plan_review_prescription_and_task(coord, doctor):
    p = own_patient(doctor)
    fu = (date.today() + timedelta(days=30)).isoformat()
    body = {'date': date.today().isoformat(), 'notes': 'Reviewed home BP readings; improving.', 'diagnosis': 'Hypertension',
            'prescription': 'Ramipril 5 mg once daily', 'plan': 'Continue BP diary; review in a month', 'followUp': fu}
    assert coord.post(f"/api/patients/{p['id']}/consultations", json=body).status_code == 403
    assert doctor.post(f"/api/patients/{other_patient(coord)['id']}/consultations", json=body).status_code == 404
    assert doctor.post(f"/api/patients/{p['id']}/consultations", json={**body, 'date': FUTURE}).status_code == 422
    r = doctor.post(f"/api/patients/{p['id']}/consultations", json=body)
    assert r.status_code == 201, r.text
    d = doctor.get(f"/api/patients/{p['id']}").json()
    assert d['reviewDue'] == fu and d['carePlan']['planText'].startswith('Continue BP diary')
    assert any(x['drug'] == 'Ramipril 5 mg once daily' for x in d['prescriptions'])
    assert any(t['title'].startswith('Arrange follow-up appointment') for t in d['tasks'])


def test_notifications_read_all(doctor):
    assert doctor.post('/api/notifications/read-all').status_code == 204
    assert doctor.get('/api/notifications').json()['unread'] == 0
    with SessionLocal() as db:
        other = db.execute(select(Notification).where(Notification.to_user != 'u-d1')).scalars().first()
    if other:
        assert doctor.post(f'/api/notifications/{other.id}/read').status_code == 404


def test_catalog(coord):
    c = coord.get('/api/catalog').json()
    assert 'HbA1c' in c['testTypes'] and c['slots'][0] == '08:00' and c['slots'][-1] == '17:30'
