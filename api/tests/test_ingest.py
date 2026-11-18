"""Phase 3: Data Import – uploads, review decisions, confirm, demo datasets, originals, and its link to care gaps."""
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import CareGapAlert, IngestionBatch, Patient, PriorityHistory

SAMPLES = Path(__file__).resolve().parents[2] / 'backend' / 'sample_uploads'


def up(client, name, data, mime='text/csv'):
    return client.post('/api/ingest/upload', files={'file': (name, data, mime)})


def confirm(client, b):
    for r in b['recordList']:
        if r['decision'] == 'pending':
            client.patch(f"/api/ingest/records/{r['id']}", json={'decision': 'skip'})
    return client.post(f"/api/ingest/batches/{b['id']}/confirm")


def test_only_coordinators(doctor, admin):
    assert doctor.get('/api/ingest/batches').status_code == 403
    assert admin.post('/api/ingest/demo/baseline/load').status_code == 403


@pytest.mark.parametrize('name,data,code', [('notes.txt', b'hello', 422), ('empty.csv', b'', 422), ('fake.pdf', b'not a pdf', 422),
                                            ('bin.csv', b'\x00\x01\x02', 422), ('bad.json', b'{oops', 422)])
def test_rejected_and_failed_files_are_kept(coord, name, data, code):
    r = up(coord, name, data)
    assert r.status_code == code
    assert r.json()['detail']['batch']['status'] in ('Rejected', 'Failed')


def test_oversized_upload(coord):
    assert up(coord, 'big.csv', b'a' * (5 * 1024 * 1024 + 1)).status_code == 413


def test_csv_review_and_confirm(coord):
    r = up(coord, 'patients_import.csv', (SAMPLES / 'patients_import.csv').read_bytes())
    assert r.status_code == 201, r.text
    b = r.json()
    st = {x['status'] for x in b['recordList']}
    assert {'matched', 'new', 'uncertain', 'duplicate', 'invalid'} <= st, st
    assert coord.post(f"/api/ingest/batches/{b['id']}/confirm").status_code == 409            # uncertain rows block confirm
    unc = next(x for x in b['recordList'] if x['status'] == 'uncertain' and x['candidates'])
    r = coord.patch(f"/api/ingest/records/{unc['id']}", json={'patientId': unc['candidates'][0]['id'], 'decision': 'import'})
    assert r.status_code == 200
    res = confirm(coord, r.json())
    assert res.status_code == 200 and res.json()['result']['imported'] >= 2
    with SessionLocal() as db:
        p = db.get(Patient, 'PT-2001')
        assert p and p.source_batch_id == b['id']
        assert db.execute(select(PriorityHistory).where(PriorityHistory.patient_id == 'PT-2001')).scalar().previous_priority is None
    assert coord.post(f"/api/ingest/batches/{b['id']}/confirm").status_code == 409            # already finalised


def test_json_and_pdf(coord, doctor):
    r = up(coord, 'clinical_records.json', (SAMPLES / 'clinical_records.json').read_bytes(), 'application/json')
    assert r.status_code == 201 and confirm(coord, r.json()).status_code == 200
    r = up(coord, 'PT-1002_HbA1c_report.pdf', (SAMPLES / 'PT-1002_HbA1c_report.pdf').read_bytes(), 'application/pdf')
    assert r.status_code == 201, r.text
    b = r.json()
    t = next(x for x in b['recordList'] if x['kind'] == 'test')
    assert t['patientId'] == 'PT-1002' and b['document']['text']
    confirm(coord, b)
    doc_id = b['document']['id']
    assert coord.get(f'/api/documents/{doc_id}/file').status_code == 200
    with SessionLocal() as db:
        own = db.get(Patient, 'PT-1002').doctor_id == 'u-d1'
    assert doctor.get(f'/api/documents/{doc_id}/file').status_code == (200 if own else 404)


def test_demo_datasets_move_priority_and_feed_care_gaps(coord):
    assert [d['id'] for d in coord.get('/api/ingest/demo').json()] == ['baseline', 'escalation', 'recovery', 'edge']
    csv_ = coord.get('/api/ingest/demo/baseline/file')
    assert csv_.status_code == 200 and b'{T' not in csv_.content
    cur = lambda pid: coord.get(f'/api/patients/{pid}').json()['priority']
    r = coord.post('/api/ingest/demo/baseline/load')
    assert r.status_code == 201 and confirm(coord, r.json()).json()['result']['failed'] == 0
    assert (cur('PT-3002'), cur('PT-3003')) == ('high', 'low')
    with SessionLocal() as db:            # imported data is rescanned at once: PT-3005 missed an appointment, PT-3002 has an abnormal result
        rules = {(a.patient_id, a.rule) for a in db.execute(select(CareGapAlert).where(CareGapAlert.status == 'Open')).scalars()}
    assert ('PT-3005', 'missed_appt') in rules and ('PT-3002', 'results_review') in rules
    b = coord.post('/api/ingest/demo/escalation/load').json()
    assert any(x['status'] == 'duplicate' and x['kind'] == 'priority' for x in b['recordList'])     # PT-3005 already High
    confirm(coord, b)
    assert cur('PT-3003') == 'high'
    confirm(coord, coord.post('/api/ingest/demo/recovery/load').json())
    assert (cur('PT-3003'), cur('PT-3002')) == ('med', 'low')
    e = coord.post('/api/ingest/demo/edge/load').json()
    assert e['pending'] == 2 and sum(1 for x in e['recordList'] if x['status'] == 'invalid') == 4
    confirm(coord, e)
    assert cur('PT-3011') == 'high'
    again = coord.post('/api/ingest/demo/recovery/load').json()
    assert all(x['status'] == 'duplicate' for x in again['recordList'])
    assert coord.post(f"/api/ingest/batches/{again['id']}/cancel").json()['status'] == 'Cancelled'
    with SessionLocal() as db:
        assert db.get(IngestionBatch, again['id']).status == 'Cancelled'


def test_edit_fields_rechecks_record(coord):
    data = b'record_type,patient_id,test_name,date,summary\ntest,PT-1001,ECG,31/02/2026,Sinus rhythm\n'
    b = up(coord, 'one_test.csv', data).json()
    r = b['recordList'][0]
    assert r['status'] == 'invalid'
    fixed = coord.patch(f"/api/ingest/records/{r['id']}", json={'fields': {'date': '2026-02-27'}}).json()['recordList'][0]
    assert fixed['status'] == 'matched' and fixed['decision'] == 'import'
    coord.post(f"/api/ingest/batches/{b['id']}/cancel")
