"""HTTP routes for file-based ingestion (/api/ingest/*). Authorised users: Care Coordinator."""
import base64, binascii, json
from . import config, db, ingest

AUTHORISED = ('coordinator',)


def batch_row(r):
    return {'id': r['id'], 'filename': r['filename'], 'type': r['file_type'], 'size': r['size_bytes'], 'sha256': r['sha256'], 'status': r['status'],
            'message': r['message'], 'uploadedBy': r['uploaded_by_name'], 'uploadedAt': r['uploaded_at'], 'confirmedAt': r['confirmed_at'],
            'method': r['extraction_method'], 'records': r['n_records'], 'imported': r['n_imported'], 'skipped': r['n_skipped'], 'failed': r['n_failed']}


def record_row(r):
    return {'id': r['id'], 'row': r['row_no'], 'kind': r['kind'], 'mapped': json.loads(r['mapped_json'] or '{}'), 'status': r['match_status'],
            'patientId': r['matched_patient_id'], 'candidates': json.loads(r['candidates_json'] or '[]'), 'issues': json.loads(r['issues_json'] or '[]'),
            'decision': r['decision'], 'result': r['result'], 'message': r['result_message'], 'saved': r['saved_entity']}


def detail(conn, bid, ApiError):
    b = conn.execute("SELECT * FROM ingestion_batches WHERE id=?", (bid,)).fetchone()
    if not b:
        raise ApiError('Batch not found', 404)
    recs = [record_row(r) for r in conn.execute("SELECT * FROM ingestion_records WHERE batch_id=? ORDER BY id", (bid,))]
    d = conn.execute("SELECT id, extracted_text, extraction_method, patient_id FROM documents WHERE batch_id=?", (bid,)).fetchone()
    out = batch_row(b)
    out['recordList'] = recs
    out['document'] = {'id': d['id'], 'text': (d['extracted_text'] or '')[:8000], 'method': d['extraction_method'], 'patientId': d['patient_id']} if d else None
    out['pending'] = sum(1 for r in recs if r['decision'] == 'pending')
    return out


def register(route, ApiError):
    def need(h, conn):
        u = h._user(conn)
        if u['role'] not in AUTHORISED:
            raise ApiError('Your role is not authorised to import patient data', 403)
        return u

    def upload(h, conn):
        u = need(h, conn)
        b = h._body()
        fname = (b.get('filename') or '').strip()
        if not fname:
            raise ApiError('No file name supplied')
        ft = ingest.detect_type(fname)
        try:
            data = base64.b64decode(b.get('contentBase64') or '', validate=True)
        except (binascii.Error, ValueError):
            raise ApiError('The file content could not be decoded')
        reason = None
        if ft not in config.ALLOWED_UPLOAD_TYPES:
            reason = f'Unsupported file type ".{ft}". Allowed: CSV, JSON, PDF.'
        elif len(data) == 0:
            reason = 'The file is empty.'
        elif len(data) > config.MAX_UPLOAD_BYTES:
            reason = f'File is {len(data)/1048576:.1f} MB – the limit is {config.MAX_UPLOAD_BYTES/1048576:.0f} MB.'
        elif ft == 'pdf' and not data.startswith(b'%PDF'):
            reason = 'The file is named .pdf but is not a valid PDF document.'
        elif ft in ('csv', 'json') and b'\x00' in data[:2048]:
            reason = f'The file is named .{ft} but appears to be binary, not text.'
        with db.WRITE_LOCK:
            conn.execute("BEGIN IMMEDIATE")
            try:
                bid = ingest.create_batch(conn, u, fname, data, ft, reject_reason=reason)
                ingest.audit(conn, u, 'Data file uploaded' if not reason else 'Data file rejected', None, bid, f'{fname} ({len(data)} bytes)' + (f': {reason}' if reason else ''))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK"); raise
        out = detail(conn, bid, ApiError)
        if reason:
            raise ApiError(reason, 422, {'batch': out})
        if out['status'] == 'Failed':
            raise ApiError(out['message'], 422, {'batch': out})
        return {'batch': out}

    def list_batches(h, conn):
        need(h, conn)
        return {'batches': [batch_row(r) for r in conn.execute("SELECT * FROM ingestion_batches ORDER BY uploaded_at DESC, rowid DESC")]}

    def get_batch(h, conn, bid):
        need(h, conn)
        return {'batch': detail(conn, bid, ApiError)}

    def patch_record(h, conn, rid):
        u = need(h, conn)
        b = h._body()
        r = conn.execute("SELECT * FROM ingestion_records WHERE id=?", (rid,)).fetchone()
        if not r:
            raise ApiError('Record not found', 404)
        bt = conn.execute("SELECT * FROM ingestion_batches WHERE id=?", (r['batch_id'],)).fetchone()
        if bt['status'] != 'Needs Review':
            raise ApiError('This batch has already been finalised', 409)
        if r['kind'] == 'unknown':
            raise ApiError('This record type is not recognised and cannot be edited', 400)
        d = json.loads(r['mapped_json'] or '{}')
        force_patient, force_new = None, False
        with db.WRITE_LOCK:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if isinstance(b.get('fields'), dict):
                    for k, v in b['fields'].items():
                        if k in ingest.KIND_FIELDS.get(r['kind'], []):
                            if v in (None, ''):
                                d.pop(k, None)
                            else:
                                d[k] = str(v).strip()
                if b.get('patientId') == 'NEW':
                    if r['kind'] != 'patient':
                        raise ApiError('Only patient records can be created as new patients', 400)
                    force_new = True
                elif b.get('patientId'):
                    force_patient = b['patientId']
                    if not conn.execute("SELECT 1 FROM patients WHERE id=?", (force_patient,)).fetchone():
                        raise ApiError('Chosen patient does not exist', 404)
                elif r['matched_patient_id']:
                    force_patient = r['matched_patient_id']
                ev = ingest.evaluate(conn, r['kind'], d, None, force_patient=force_patient, force_new=force_new)
                decision = b.get('decision') if b.get('decision') in ('import', 'skip') else ev['decision']
                if ev['match_status'] in ('invalid', 'duplicate') and b.get('decision') != 'import':
                    decision = 'skip'
                if ev['match_status'] == 'invalid':
                    decision = 'skip'
                if ev['match_status'] == 'uncertain' and decision == 'import':
                    raise ApiError('Choose which patient this record belongs to (or create a new patient) before importing it', 400)
                res_ = 'failed' if ev['match_status'] == 'invalid' else None
                conn.execute("UPDATE ingestion_records SET mapped_json=?, match_status=?, matched_patient_id=?, candidates_json=?, issues_json=?, decision=?, result=?, result_message=? WHERE id=?",
                             (json.dumps(d), ev['match_status'], ev['matched_patient_id'], json.dumps(ev['candidates']), json.dumps(ev['issues']), decision, res_,
                              '; '.join(i['msg'] for i in ev['issues'] if i['level'] == 'error') if res_ else None, rid))
                ingest.audit(conn, u, 'Import record reviewed', ev['matched_patient_id'], r['batch_id'], f'row {r["row_no"]}: decision={decision}, match={ev["match_status"]}')
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK"); raise
        return {'batch': detail(conn, r['batch_id'], ApiError)}

    def confirm(h, conn, bid):
        u = need(h, conn)
        try:
            res = ingest.confirm_batch(conn, u, bid)
        except ingest.IngestError as e:
            raise ApiError(str(e), 409)
        return {'result': res, 'batch': detail(conn, bid, ApiError)}

    def cancel(h, conn, bid):
        u = need(h, conn)
        b = conn.execute("SELECT status FROM ingestion_batches WHERE id=?", (bid,)).fetchone()
        if not b:
            raise ApiError('Batch not found', 404)
        if b['status'] != 'Needs Review':
            raise ApiError('Only batches awaiting review can be cancelled', 409)
        with db.WRITE_LOCK:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE ingestion_batches SET status='Cancelled', message='Cancelled by reviewer – nothing was imported' WHERE id=?", (bid,))
            conn.execute("UPDATE ingestion_records SET result='skipped', result_message='Batch cancelled' WHERE batch_id=? AND result IS NULL", (bid,))
            ingest.audit(conn, u, 'Data import cancelled', None, bid, '')
            conn.execute("COMMIT")
        return {'batch': detail(conn, bid, ApiError)}

    def file(h, conn, did):
        u = h._user(conn)
        d = conn.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
        if not d:
            raise ApiError('Document not found', 404)
        allowed = u['role'] == 'coordinator'
        if u['role'] == 'doctor' and d['patient_id']:
            allowed = bool(conn.execute("SELECT 1 FROM patients WHERE id=? AND doctor_id=?", (d['patient_id'], u['id'])).fetchone())
        if not allowed:
            raise ApiError('Not authorised to open this document', 403)
        from pathlib import Path
        data = Path(d['stored_path']).read_bytes()
        h.send_response(200)
        h.send_header('Content-Type', {'pdf': 'application/pdf', 'csv': 'text/csv', 'json': 'application/json'}.get(d['file_type'], 'application/octet-stream'))
        h.send_header('Content-Disposition', f'attachment; filename="{d["filename"]}"')
        h.send_header('Content-Length', str(len(data)))
        h.end_headers(); h.wfile.write(data)

    route('POST', r'/api/ingest/upload', upload)
    route('GET', r'/api/ingest/batches', list_batches)
    route('GET', r'/api/ingest/batches/([A-Za-z0-9_-]+)', get_batch)
    route('PATCH', r'/api/ingest/records/(\d+)', patch_record)
    route('POST', r'/api/ingest/batches/([A-Za-z0-9_-]+)/confirm', confirm)
    route('POST', r'/api/ingest/batches/([A-Za-z0-9_-]+)/cancel', cancel)
    route('GET', r'/api/ingest/documents/([A-Za-z0-9_-]+)/file', file)
