"""Background jobs and their scheduler.

Jobs
  deliver_reminders  – sends every due reminder (SIMULATED: marks it Delivered or Failed; nothing leaves the system)
  scan_care_gaps     – re-runs the care-gap rules for all patients (catches gaps that appear with the passing of time,
                       e.g. a review date that has just gone by – actions in the app already rescan the affected patient)

No job calls the LLM. AI wording (Gemini) runs only when a person asks for it – POST /api/care-gaps/{id}/recommendation
(the "Generate / Regenerate with AI" button). Scans, imports, demo loads, list views and scheduler runs never call the model.

Runners
  embedded  – a daemon thread started with the API (settings.scheduler == 'embedded'; single instance / development)
  worker    – `python -m app.worker` as its own process (set CAREFLOW_SCHEDULER=off on the API instances)
The last run of each job is stored in app_settings['jobs'] so the UI can show it.
"""
import hashlib
import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import AppSetting, Reminder
from app.services import care_gaps
from app.services.common import audit, utcnow

log = logging.getLogger('careflow.jobs')
_run_lock = threading.Lock()          # one run at a time inside this process


def _simulated_outcome(reminder_id: str) -> str:
    # deterministic: about 1 in 9 simulated deliveries fails, so the UI's failure handling can be demonstrated
    return 'Failed' if int(hashlib.sha256(reminder_id.encode()).hexdigest(), 16) % 9 == 0 else 'Delivered'


def deliver_reminders(db: Session) -> dict:
    now = utcnow()
    due = list(db.execute(select(Reminder).where(Reminder.status == 'Scheduled', Reminder.scheduled_for <= now).with_for_update(skip_locked=True)).scalars())
    stats = {'Delivered': 0, 'Failed': 0}
    for r in due:
        r.status, r.sent_at = _simulated_outcome(r.id), now
        stats[r.status] += 1
    if due:
        audit(db, None, 'Reminder delivery run (simulated)', detail=f'{len(due)} due reminder(s): {stats["Delivered"]} delivered, {stats["Failed"]} failed')
    db.commit()
    return {'processed': len(due), **{k.lower(): v for k, v in stats.items()}}


def scan_care_gaps(db: Session) -> dict:
    return care_gaps.rescan(db, None)


# Phase 0 (on-demand AI): the former 'word_recommendations' job and kick_wording() background thread were removed –
# no scheduled or automatic job may call the LLM.
JOBS = {'deliver_reminders': deliver_reminders, 'scan_care_gaps': scan_care_gaps}


def run_all(trigger: str = 'scheduler') -> dict:
    if not _run_lock.acquire(blocking=False):
        return {'skipped': 'a run is already in progress'}
    try:
        results = {}
        for name, fn in JOBS.items():
            with SessionLocal() as db:
                try:
                    results[name] = {'ok': True, 'at': utcnow().isoformat(), 'trigger': trigger, 'result': fn(db)}
                except Exception as e:                       # a failing job must not stop the others
                    db.rollback()
                    log.exception('Job %s failed', name)
                    results[name] = {'ok': False, 'at': utcnow().isoformat(), 'trigger': trigger, 'error': str(e)[:300]}
        with SessionLocal() as db:
            row = db.get(AppSetting, 'jobs')
            if row is None:
                db.add(AppSetting(key='jobs', value=results))
            else:
                row.value = {**(row.value or {}), **results}
            db.commit()
        return results
    finally:
        _run_lock.release()


def last_runs(db: Session) -> dict:
    row = db.get(AppSetting, 'jobs')
    return {k: v for k, v in (row.value or {}).items() if k in JOBS} if row else {}      # hides runs of removed jobs


class EmbeddedScheduler:
    def __init__(self, interval: int):
        self.interval, self._stop = interval, threading.Event()
        self._t = threading.Thread(target=self._loop, name='careflow-scheduler', daemon=True)

    def _loop(self):
        delay = 5                                   # first run shortly after start-up, then every `interval` seconds
        while not self._stop.wait(delay):
            delay = self.interval
            try:
                run_all('scheduler')
            except Exception:
                log.exception('Scheduled run failed')

    def start(self):
        self._t.start()

    def stop(self):
        self._stop.set()


def maybe_start_embedded() -> EmbeddedScheduler | None:
    cfg = get_settings()
    if cfg.scheduler != 'embedded' or cfg.env == 'test':
        return None
    s = EmbeddedScheduler(cfg.scheduler_interval_seconds)
    s.start()
    log.info('Embedded scheduler started (every %ss)', cfg.scheduler_interval_seconds)
    return s
