"""AI Care Assistant (coordinators and doctors). Template-based chat agents (no LLM); the patient AI summary can additionally be
written by the LLM summary agent on request. Nothing is executed without approval."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.routes.care_gaps import alerts_out
from app.models import AssistantMessage, AssistantProposal, CareGapAlert, User
from app.services import assistant as svc
from app.services import summary_agent
from app.services.common import audit

router = APIRouter(prefix='/api/assistant', tags=['ai assistant'])


class AskIn(BaseModel):
    text: str = Field(min_length=2, max_length=500)
    patientId: str | None = None
    ai: bool = False                     # "Ask AI": answer with the LLM answer agent (one request); otherwise template agents


def _proposal_out(db, x: AssistantProposal) -> dict:
    names = dict(db.execute(select(User.id, User.name)).all())
    return {'id': x.id, 'type': x.type, 'patientId': x.patient_id, 'title': x.title, 'assignee': x.assignee, 'assigneeName': names.get(x.assignee),
            'due': x.due, 'priority': x.priority, 'channel': x.channel, 'message': x.message, 'status': x.status, 'resultRef': x.result_ref}


def _message_out(db, m: AssistantMessage) -> dict:
    """Live-resolve action blocks so buttons reflect the current state (an alert may have been actioned since)."""
    blocks = []
    for b in (m.payload or {}).get('blocks', []):
        if b['type'] == 'gapActions':
            alerts = [a for a in db.execute(select(CareGapAlert).where(CareGapAlert.id.in_(b['alertIds']), CareGapAlert.status == 'Open')).scalars()]
            if alerts:
                blocks.append({'type': 'gapActions', 'alerts': [a.model_dump(by_alias=True, mode='json') for a in alerts_out(db, alerts)]})
        elif b['type'] == 'proposals':
            blocks.append({'type': 'proposals', 'proposals': [_proposal_out(db, x) for x in db.execute(select(AssistantProposal).where(AssistantProposal.id.in_(b['proposalIds']))).scalars()]})
        else:
            blocks.append(b)
    pl = m.payload or {}
    return {'id': m.id, 'ts': m.ts, 'role': m.role, 'text': m.text, 'patientId': m.patient_id, 'blocks': blocks, 'trace': pl.get('trace', []),
            'ai': bool(pl.get('ai')), 'model': pl.get('model'), 'offerAi': bool(pl.get('offerAi'))}


@router.get('/prompts')
def prompts(user: CurrentUser, db: DB):
    return svc.prompts(db, user)


@router.get('/messages')
def messages(user: CurrentUser, db: DB):
    return [_message_out(db, m) for m in svc.history(db, user)]


@router.post('/messages')
def ask(body: AskIn, user: CurrentUser, db: DB):
    return _message_out(db, svc.ask(db, user, body.text, body.patientId, body.ai))


@router.delete('/messages', status_code=204)
def clear(user: CurrentUser, db: DB):
    svc.clear(db, user)


@router.get('/patients/{patient_id}/summary')
def summary(patient_id: str, user: CurrentUser, db: DB):
    """Template summary (no LLM) + the stored AI summary if it still matches the records (`ai.status`). Never calls the model."""
    b = summary_agent.summary(db, user, patient_id)
    audit(db, user, 'AI summary generated', patient_id=patient_id, detail=f'Template summary agent (no LLM) · {len(b["evidence"])} sources cited')
    db.commit()
    return b


@router.post('/patients/{patient_id}/summary/ai')
def summary_ai(patient_id: str, user: CurrentUser, db: DB):
    """Write the AI summary now – one click, one model request (Context agent → Summary agent → verifier).
    503 switched off · 429 limit / cooldown · 502 provider failure or withheld by the checks (the template stays)."""
    svc._need(user)
    b, ok = summary_agent.generate(db, user, patient_id)
    if ok:
        audit(db, user, 'AI summary written (LLM)', patient_id=patient_id, detail=f'Summary agent · {b["ai"].get("model")} · {len(b["evidence"])} sources')
    db.commit()
    if not ok:
        raise HTTPException(502, f'The AI summary could not be written: {b["ai"].get("error") or b["ai"].get("lastError")}')
    return b


@router.post('/proposals/{proposal_id}/approve')
def approve(proposal_id: str, user: CurrentUser, db: DB):
    return _proposal_out(db, svc.approve(db, user, proposal_id))


@router.post('/proposals/{proposal_id}/reject')
def reject(proposal_id: str, user: CurrentUser, db: DB):
    return _proposal_out(db, svc.reject(db, user, proposal_id))
