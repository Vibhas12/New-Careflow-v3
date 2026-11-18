"""Demo scenario selection for the sign-in screen (available only when demo mode is enabled)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import demo_data
from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.services.common import audit

router = APIRouter(prefix='/api/demo', tags=['demo'])


class LoadIn(BaseModel):
    scenario: str


@router.get('/scenarios')
def scenarios(db: DB):
    """Public (shown before sign-in). Returns only scenario descriptions and whether any patient data exists."""
    if not get_settings().demo_enabled:
        return {'enabled': False, 'scenarios': [], 'hasData': None}
    return {'enabled': True, 'hasData': demo_data.patient_count(db) > 0,
            'scenarios': [{k: s[k] for k in ('id', 'title', 'summary')} for s in demo_data.SCENARIOS]}


@router.post('/load')
def load(body: LoadIn, user: CurrentUser, db: DB):
    """Replace all patient-related data with the chosen scenario (requires a signed-in user; demo mode only)."""
    if not get_settings().demo_enabled:
        raise HTTPException(404, 'Not found')
    if demo_data.find(body.scenario) is None:
        raise HTTPException(422, 'Unknown demo scenario')
    result = demo_data.load(db, body.scenario, user)
    audit(db, user, 'Demo scenario loaded', detail=f"{result['title']} – {result['patients']} patient(s)")
    db.commit()
    return result
