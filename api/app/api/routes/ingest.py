"""Data Import (Care Coordinators only): upload or one-click demo dataset → review → confirm / cancel, plus history and originals."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, require_roles
from app.core.config import get_settings
from app.ingest import demo, pipeline
from app.ingest.parsing import IngestError
from app.models import Document, IngestionBatch, IngestionRecord, Patient, User
from app.schemas import BatchDetail, BatchOut, ConfirmOut, DemoDataset, IngestRecordOut, RecordReviewIn
from app.services import care_gaps, import_agents

router = APIRouter(prefix='/api/ingest', tags=['data import'], dependencies=[Depends(require_roles('coordinator'))])
docs_router = APIRouter(prefix='/api/documents', tags=['data import'])


def batch_out(db, b: IngestionBatch) -> dict:
    who = db.get(User, b.uploaded_by) if b.uploaded_by else None
    return dict(id=b.id, filename=b.filename, type=b.file_type, size=b.size_bytes, sha256=b.sha256, status=b.status, message=b.message,
                uploaded_by=who.name if who else None, uploaded_at=b.uploaded_at, confirmed_at=b.confirmed_at, method=b.extraction_method,
                records=b.n_records or 0, imported=b.n_imported or 0, skipped=b.n_skipped or 0, failed=b.n_failed or 0)


def detail(db, bid: str) -> BatchDetail:
    b = db.get(IngestionBatch, bid)
    if b is None:
        raise HTTPException(404, 'Batch not found')
    recs = list(db.execute(select(IngestionRecord).where(IngestionRecord.batch_id == bid).order_by(IngestionRecord.id)).scalars())
    d = db.execute(select(Document).where(Document.batch_id == bid)).scalar()
    unknown = import_agents.unknown_columns(db, b) if b.file_type in ('csv', 'json') and b.status == 'Needs Review' else []
    return BatchDetail(**batch_out(db, b), record_list=[IngestRecordOut(
        id=r.id, row=r.row_no, kind=r.kind, mapped=r.mapped or {}, status=r.match_status, patient_id=r.matched_patient_id, candidates=r.candidates or [],
        issues=r.issues or [], decision=r.decision, result=r.result, message=r.result_message, saved=r.saved_entity, ai_suggestion=r.ai_suggestion) for r in recs],
        document={'id': d.id, 'text': (d.extracted_text or '')[:8000], 'method': d.extraction_method, 'patientId': d.patient_id} if d else None,
        pending=sum(1 for r in recs if r.decision == 'pending'), unknown_columns=unknown, ai_mapping=b.ai_mapping)


def _created(db, b: IngestionBatch) -> BatchDetail:
    out = detail(db, b.id)
    if b.status in ('Rejected', 'Failed'):
        raise HTTPException(422, {'message': b.message, 'batch': out.model_dump(by_alias=True, mode='json')})
    return out


@router.post('/upload', response_model=BatchDetail, status_code=201)
async def upload(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    limit = get_settings().max_upload_bytes
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):          # stop reading as soon as the limit is exceeded
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f'File is larger than {limit // 1048576} MB')
        chunks.append(chunk)
    return _created(db, pipeline.create_batch(db, user, file.filename or 'upload', b''.join(chunks)))


@router.get('/demo', response_model=list[DemoDataset])
def demo_list():
    return demo.manifest()


@router.post('/demo/{dataset_id}/load', response_model=BatchDetail, status_code=201)
def demo_load(dataset_id: str, user: CurrentUser, db: DB):
    ds = demo.find(dataset_id)
    if ds is None:
        raise HTTPException(404, 'Demo dataset not found')
    return _created(db, pipeline.create_batch(db, user, demo.filename(ds), demo.render(ds), label='Demo dataset loaded'))


@router.get('/demo/{dataset_id}/file')
def demo_file(dataset_id: str):
    ds = demo.find(dataset_id)
    if ds is None:
        raise HTTPException(404, 'Demo dataset not found')
    return Response(demo.render(ds), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="{demo.filename(ds)}"'})


@router.get('/batches', response_model=list[BatchOut])
def batches(db: DB, limit: int = 100):
    return [batch_out(db, b) for b in db.execute(select(IngestionBatch).order_by(IngestionBatch.uploaded_at.desc()).limit(min(limit, 500))).scalars()]


@router.get('/batches/{bid}', response_model=BatchDetail)
def get_batch(bid: str, db: DB):
    return detail(db, bid)


@router.patch('/records/{rid}', response_model=BatchDetail)
def review(rid: int, body: RecordReviewIn, user: CurrentUser, db: DB):
    r = db.get(IngestionRecord, rid)
    if r is None:
        raise HTTPException(404, 'Record not found')
    try:
        pipeline.review_record(db, user, r, fields=body.fields, patient_id=body.patient_id, decision=body.decision)
    except IngestError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    return detail(db, r.batch_id)


# ---------------------------------------------------------------- phase 5: AI help inside review (on request only)
def _record(db, rid: int) -> IngestionRecord:
    r = db.get(IngestionRecord, rid)
    if r is None:
        raise HTTPException(404, 'Record not found')
    return r


def _batch(db, bid: str) -> IngestionBatch:
    b = db.get(IngestionBatch, bid)
    if b is None:
        raise HTTPException(404, 'Batch not found')
    return b


@router.post('/records/{rid}/ai-extract', response_model=BatchDetail)
def ai_extract(rid: int, user: CurrentUser, db: DB):
    """Document-extraction agent (one model request) – stores a suggestion; nothing changes until Apply. 502 if failed / withheld."""
    r = _record(db, rid)
    try:
        ok = import_agents.extract(db, user, r)
    except IngestError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    if not ok:
        raise HTTPException(502, f'AI extraction not available for this row: {(r.ai_suggestion or {}).get("error")}')
    return detail(db, r.batch_id)


@router.post('/records/{rid}/ai-apply', response_model=BatchDetail)
def ai_apply(rid: int, user: CurrentUser, db: DB):
    r = _record(db, rid)
    try:
        import_agents.apply_extraction(db, user, r)
    except IngestError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    return detail(db, r.batch_id)


@router.post('/batches/{bid}/ai-map', response_model=BatchDetail)
def ai_map(bid: str, user: CurrentUser, db: DB):
    """Column-mapping agent (one model request, column names and value shapes only) – stores a suggestion."""
    b = _batch(db, bid)
    try:
        ok = import_agents.suggest_mapping(db, user, b)
    except IngestError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    if not ok:
        raise HTTPException(502, f'AI column mapping not available: {(b.ai_mapping or {}).get("error")}')
    return detail(db, bid)


@router.post('/batches/{bid}/ai-map/apply', response_model=BatchDetail)
def ai_map_apply(bid: str, user: CurrentUser, db: DB):
    """Fill empty fields from the mapped columns; every changed record is re-checked for matches and duplicates."""
    b = _batch(db, bid)
    try:
        import_agents.apply_mapping(db, user, b)
    except IngestError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    return detail(db, bid)


@router.post('/batches/{bid}/confirm', response_model=ConfirmOut)
def confirm(bid: str, user: CurrentUser, db: DB):
    try:
        result, touched = pipeline.confirm_batch(db, user, bid)
    except IngestError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    care_gaps.rescan(db, sorted(touched))                 # imported data feeds care-gap detection straight away
    return ConfirmOut(result=result, batch=detail(db, bid))


@router.post('/batches/{bid}/cancel', response_model=BatchDetail)
def cancel(bid: str, user: CurrentUser, db: DB):
    try:
        pipeline.cancel_batch(db, user, bid)
    except IngestError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    return detail(db, bid)


@docs_router.get('/{doc_id}/file')
def original_file(doc_id: str, user: CurrentUser, db: DB):
    """Coordinators: any original. Doctors: originals attached to their own patients."""
    d = db.get(Document, doc_id)
    if d is None:
        raise HTTPException(404, 'Document not found')
    ok = user.role == 'coordinator' or (user.role == 'doctor' and d.patient_id and
                                         db.execute(select(Patient.id).where(Patient.id == d.patient_id, Patient.doctor_id == user.id)).first())
    if not ok:
        raise HTTPException(404, 'Document not found')
    p = Path(d.stored_path)
    if not p.is_file():
        raise HTTPException(410, 'The original file is no longer available on the server')
    media = {'pdf': 'application/pdf', 'csv': 'text/csv', 'json': 'application/json'}.get(d.file_type or '', 'application/octet-stream')
    return FileResponse(p, media_type=media, filename=d.filename)
