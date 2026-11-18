"""Data Import agents (multi-agent phase 5): document extraction and column mapping – on request only, inside review.
Fake LLM, no network."""
import json
from pathlib import Path

import pytest

from app.services import import_agents as ia

SAMPLES = Path(__file__).resolve().parents[2] / 'backend' / 'sample_uploads'
GOOD = ia.ReportFields(test_name='HbA1c', report_date='12/11/2026', findings='HbA1c 48 mmol/mol (reference 20-42). Fasting glucose 6.4 mmol/L.',
                       abnormal='not stated', notes_for_reviewer='')
CSV = (b'record_type,patient_ref_no,christian_name,family,birth,clinic,illness\n'
       b'patient,PT-5101,Asha,Menon,1980-02-03,Cardiology,Hypertension\n'
       b'patient,PT-5102,Ravi,Shah,1975-07-21,Neurology,Migraine\n')
MAP = ia.Mappings(mappings=[ia.ColumnMapping(header=h, field=f, reason='shape matches') for h, f in
                            (('patient_ref_no', 'patient_id'), ('christian_name', 'first_name'), ('family', 'last_name'), ('birth', 'dob'),
                             ('clinic', 'department'), ('illness', 'primary_condition'))])


def up(client, name, data, mime):
    r = client.post('/api/ingest/upload', files={'file': (name, data, mime)})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def pdf_batch(coord):
    b = up(coord, 'PT-1002_HbA1c_report.pdf', (SAMPLES / 'PT-1002_HbA1c_report.pdf').read_bytes(), 'application/pdf')
    yield b, next(r for r in b['recordList'] if r['kind'] == 'test')
    coord.post(f"/api/ingest/batches/{b['id']}/cancel")


@pytest.fixture
def csv_batch(coord):
    b = up(coord, 'odd_headers.csv', CSV, 'text/csv')
    yield b
    coord.post(f"/api/ingest/batches/{b['id']}/cancel")


# ---------------------------------------------------------------- document extraction
def test_upload_and_review_never_call_the_model(coord, fake_llm, pdf_batch, csv_batch):
    coord.get(f"/api/ingest/batches/{pdf_batch[0]['id']}")
    coord.get(f"/api/ingest/batches/{csv_batch['id']}")
    assert fake_llm.calls == []


def test_extract_is_deidentified_and_applied_only_on_request(coord, fake_llm, pdf_batch):
    fake_llm.respond(ia.ReportFields, GOOD)
    b, rec = pdf_batch
    r = coord.post(f"/api/ingest/records/{rec['id']}/ai-extract")
    assert r.status_code == 200, r.text
    after = next(x for x in r.json()['recordList'] if x['id'] == rec['id'])
    s = after['aiSuggestion']
    assert s['status'] == 'ready' and s['fields'] == {'test_name': 'HbA1c', 'date': '2026-11-12', 'summary': GOOD.findings} and s['model'] == 'fake-llm'
    assert after['mapped'] == rec['mapped']                                              # nothing changes until Apply
    sent = fake_llm.calls[0]['prompt']
    for secret in ('Emma', 'Parker', 'PT-1002', 'Sarah Wilson', 'Wilson'):
        assert secret not in sent, secret
    assert 'HbA1c 48 mmol/mol' in sent and '[identity line removed]' in sent
    r = coord.post(f"/api/ingest/records/{rec['id']}/ai-apply")
    assert r.status_code == 200, r.text
    applied = next(x for x in r.json()['recordList'] if x['id'] == rec['id'])
    assert applied['mapped']['date'] == '2026-11-12' and applied['mapped']['summary'] == GOOD.findings and applied['aiSuggestion']['applied']
    assert applied['patientId'] == 'PT-1002'                                              # identity / matching untouched
    assert coord.post(f"/api/ingest/records/{rec['id']}/ai-apply").status_code == 409     # only once
    assert len(fake_llm.calls) == 1


@pytest.mark.parametrize('change, why', [
    ({'test_name': 'Lipid Profile'}, 'does not appear in the document'),
    ({'findings': 'HbA1c 64 mmol/mol (reference 20-42).'}, 'value or dose'),
    ({'report_date': '15/11/2026'}, 'date that is not in the facts'),
    ({'findings': 'HbA1c 48 mmol/mol, consistent with poorly controlled diabetes.'}, 'interprets findings'),
    ({'findings': 'The patient feels much better and walks daily without symptoms.'}, 'not taken from the document'),
])
def test_unsupported_extraction_is_withheld(coord, fake_llm, pdf_batch, change, why):
    fake_llm.respond(ia.ReportFields, GOOD.model_copy(update=change))
    b, rec = pdf_batch
    r = coord.post(f"/api/ingest/records/{rec['id']}/ai-extract")
    assert r.status_code == 502 and why in r.json()['detail']
    s = next(x for x in coord.get(f"/api/ingest/batches/{b['id']}").json()['recordList'] if x['id'] == rec['id'])['aiSuggestion']
    assert s['status'] == 'withheld' and 'fields' not in s
    assert coord.post(f"/api/ingest/records/{rec['id']}/ai-apply").status_code == 409     # nothing to apply


def test_unsupported_abnormal_flag_is_dropped_not_the_whole_suggestion(coord, fake_llm, pdf_batch):
    """Seen live: Gemini compared 48 with the 20-42 reference range and said 'abnormal' – the document never says so."""
    fake_llm.respond(ia.ReportFields, GOOD.model_copy(update={'abnormal': 'yes'}))
    b, rec = pdf_batch
    r = coord.post(f"/api/ingest/records/{rec['id']}/ai-extract")
    assert r.status_code == 200, r.text
    s = next(x for x in r.json()['recordList'] if x['id'] == rec['id'])['aiSuggestion']
    assert s['status'] == 'ready' and 'abnormal' not in s['fields'] and 'flag was removed' in s['notes']
    assert s['fields']['test_name'] == 'HbA1c'


def test_extract_only_for_pdf_report_rows_and_coordinators(coord, doctor, fake_llm, csv_batch):
    rid = csv_batch['recordList'][0]['id']
    assert coord.post(f'/api/ingest/records/{rid}/ai-extract').status_code == 409
    assert doctor.post(f'/api/ingest/records/{rid}/ai-extract').status_code == 403
    assert fake_llm.calls == []


# ---------------------------------------------------------------- column mapping
def test_mapping_sends_names_and_shapes_only_and_fills_empty_fields(coord, fake_llm, csv_batch):
    assert {c['header'] for c in csv_batch['unknownColumns']} == {'patient_ref_no', 'christian_name', 'family', 'birth', 'clinic', 'illness'}
    assert all(r['status'] == 'invalid' for r in csv_batch['recordList'])                 # unusable without mapping
    fake_llm.respond(ia.Mappings, MAP)
    r = coord.post(f"/api/ingest/batches/{csv_batch['id']}/ai-map")
    assert r.status_code == 200, r.text
    assert r.json()['aiMapping']['status'] == 'ready' and all(x['status'] == 'invalid' for x in r.json()['recordList'])   # not applied yet
    sent = fake_llm.calls[0]['prompt']
    for value in ('Asha', 'Menon', 'PT-5101', '1980-02-03', 'Hypertension', 'Cardiology', 'Migraine'):
        assert value not in sent.split('"targets"')[0], value                             # no values (field names may mention departments)
    cols = {c['header']: c['shape'] for c in json.loads(sent.split('Facts (JSON):\n', 1)[1])['columns']}
    assert cols['birth'] == 'date' and cols['patient_ref_no'] == 'patient ID format (PT-####)'
    r = coord.post(f"/api/ingest/batches/{csv_batch['id']}/ai-map/apply")
    assert r.status_code == 200, r.text
    recs = r.json()['recordList']
    assert {x['status'] for x in recs} == {'new'} and recs[0]['mapped']['first_name'] in ('Asha', 'Ravi')
    assert recs[0]['mapped']['dob'] in ('1980-02-03', '1975-07-21') and r.json()['aiMapping']['applied']
    assert coord.post(f"/api/ingest/batches/{csv_batch['id']}/ai-map/apply").status_code == 409


@pytest.mark.parametrize('bad, why', [
    ([('clinic', 'test_name')], 'not valid for patient records'),
    ([('christian_name', 'first_name'), ('family', 'first_name')], 'same field'),
    ([('surname_typo', 'last_name')], 'not in the file'),
])
def test_invalid_mapping_is_withheld(coord, fake_llm, csv_batch, bad, why):
    fake_llm.respond(ia.Mappings, ia.Mappings(mappings=[ia.ColumnMapping(header=h, field=f, reason='x') for h, f in bad]))
    r = coord.post(f"/api/ingest/batches/{csv_batch['id']}/ai-map")
    assert r.status_code == 502 and why in r.json()['detail']
    assert coord.get(f"/api/ingest/batches/{csv_batch['id']}").json()['aiMapping']['status'] == 'withheld'
    assert coord.post(f"/api/ingest/batches/{csv_batch['id']}/ai-map/apply").status_code == 409


def test_mapping_switched_off(coord, fake_llm, csv_batch, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'agents_disabled', ['import_map'])
    assert coord.post(f"/api/ingest/batches/{csv_batch['id']}/ai-map").status_code == 503 and fake_llm.calls == []
