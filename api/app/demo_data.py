"""Demo scenarios chosen on the sign-in screen (demo mode only – disabled when CAREFLOW_ENV=production).

The database starts with staff accounts and settings only. Choosing a scenario REPLACES all patient-related data
(patients, clinical records, tasks, alerts, imports, audit and priority history) with exactly that scenario:

  empty          no patient data
  baseline       demo dataset 1 (PT-3001 … PT-3010)
  escalation     datasets 1 → 2
  recovery       datasets 1 → 2 → 3
  full           datasets 1 → 2 → 3 → 4 (incl. the data-quality examples)
  v2             the 15-patient V2 demo set (backend/seed/seed_data.json)

Datasets are loaded through the normal import pipeline (validate → match → confirm) by a Care Coordinator account,
so they behave exactly like files imported in Data Import. Records that would need a human match decision are skipped.
"""
import logging

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Base
from app.ingest import demo, pipeline
from app.models import IngestionRecord, Patient, User
from app.services import care_gaps

log = logging.getLogger('careflow.demo')

SCENARIOS = [
    {'id': 'empty', 'title': 'Empty – no patient data', 'summary': 'Start with a clean system and add patients through Data Import.', 'datasets': []},
    {'id': 'baseline', 'title': 'Baseline – 10 new patients', 'summary': 'Demo dataset 1: PT-3001 … PT-3010 with appointments, notes, results, referrals and tasks.',
     'datasets': ['baseline']},
    {'id': 'escalation', 'title': 'Baseline + Escalation', 'summary': 'Datasets 1 → 2: abnormal results and emergency visits raise priority for 6 patients.',
     'datasets': ['baseline', 'escalation']},
    {'id': 'recovery', 'title': 'Baseline + Escalation + Recovery', 'summary': 'Datasets 1 → 2 → 3: follow-ups done, results back in range, priority lowered again.',
     'datasets': ['baseline', 'escalation', 'recovery']},
    {'id': 'full', 'title': 'All demo datasets', 'summary': 'Datasets 1 → 4, including a new patient and the data-quality examples.',
     'datasets': ['baseline', 'escalation', 'recovery', 'edge']},
    {'id': 'v2', 'title': 'V2 demo set – 15 patients', 'summary': 'The original V2 prototype patients with their full history (PT-1001 … PT-1015).', 'datasets': []},
]
KEEP = {'users', 'user_departments', 'departments', 'sessions', 'app_settings'}


def find(scenario_id: str) -> dict | None:
    return next((s for s in SCENARIOS if s['id'] == scenario_id), None)


def patient_count(db: Session) -> int:
    return db.execute(select(func.count(Patient.id))).scalar_one()


def _immutable_triggers(db: Session, create: bool) -> None:
    pg = db.get_bind().dialect.name == 'postgresql'
    if pg:
        db.execute(text('CREATE TRIGGER priority_history_no_change BEFORE UPDATE OR DELETE ON priority_history FOR EACH ROW EXECUTE FUNCTION priority_history_immutable()')
                   if create else text('DROP TRIGGER IF EXISTS priority_history_no_change ON priority_history'))
    elif create:
        db.execute(text("CREATE TRIGGER priority_history_no_update BEFORE UPDATE ON priority_history BEGIN SELECT RAISE(ABORT, 'priority_history is immutable'); END;"))
        db.execute(text("CREATE TRIGGER priority_history_no_delete BEFORE DELETE ON priority_history BEGIN SELECT RAISE(ABORT, 'priority_history is immutable'); END;"))
    else:
        db.execute(text('DROP TRIGGER IF EXISTS priority_history_no_update'))
        db.execute(text('DROP TRIGGER IF EXISTS priority_history_no_delete'))


def reset(db: Session) -> None:
    """Delete every patient-related row (demo mode only). The append-only guard on priority_history is lifted for the
    duration of this transaction and restored before it commits."""
    if not get_settings().demo_enabled:
        raise PermissionError('Demo reset is disabled in this environment')
    _immutable_triggers(db, create=False)
    for table in reversed(Base.metadata.sorted_tables):          # children first, so foreign keys stay valid
        if table.name not in KEEP:
            db.execute(delete(table))
    db.execute(text("DELETE FROM app_settings WHERE key IN ('jobs', 'seeded_on')"))
    _immutable_triggers(db, create=True)
    db.commit()
    for f in get_settings().upload_dir.glob('*'):                # preserved originals of the previous scenario
        if f.is_file():
            f.unlink(missing_ok=True)
    log.warning('Demo data reset – all patient-related records deleted')


def _importer(db: Session, user: User) -> User:
    if user.role == 'coordinator':
        return user
    c = db.execute(select(User).where(User.role == 'coordinator', User.active.is_(True)).order_by(User.id)).scalars().first()
    if c is None:
        raise RuntimeError('No active Care Coordinator account to import the demo data')
    return c


def load(db: Session, scenario_id: str, user: User) -> dict:
    sc = find(scenario_id)
    if sc is None:
        raise KeyError(scenario_id)
    reset(db)
    if sc['id'] == 'v2':
        from app.seed import seed_clinical
        seed_clinical(db)
    importer = _importer(db, user)
    summary = []
    for ds_id in sc['datasets']:
        ds = demo.find(ds_id)
        b = pipeline.create_batch(db, importer, demo.filename(ds), demo.render(ds), label=f'Demo dataset loaded at sign-in by {user.name}')
        for r in db.execute(select(IngestionRecord).where(IngestionRecord.batch_id == b.id, IngestionRecord.decision == 'pending')).scalars():
            r.decision = 'skip'                                   # uncertain matches always wait for a person – skip them here
        db.commit()
        res, _ = pipeline.confirm_batch(db, importer, b.id)
        summary.append({'dataset': ds['title'], **res})
    care_gaps.rescan(db, None)
    return {'scenario': sc['id'], 'title': sc['title'], 'patients': patient_count(db), 'imports': summary}
