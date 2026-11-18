"""CareFlow API (FastAPI). Run:  uvicorn app.main:app --reload   (from the api/ folder)"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from contextlib import asynccontextmanager

from app.api.routes import appointments, assistant, auth, care_gaps, dashboard, demo, diagnostics, ingest, notifications, patients, system, tasks
from app.core.config import get_settings
from app.jobs import maybe_start_embedded


def _ensure_reference_data():
    """Staff accounts + settings on an empty database, so sign-in works. Never creates patient data."""
    from app.db import SessionLocal
    from app.seed import seed_reference
    try:
        with SessionLocal() as db:
            if seed_reference(db):
                log.info('Created staff accounts and settings (no patient data)')
    except Exception:                       # e.g. migrations not applied yet
        log.exception('Could not prepare reference data – run `alembic upgrade head`')


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().env != 'test':
        _ensure_reference_data()
    sched = maybe_start_embedded()          # background jobs (reminders, care-gap scan) unless a separate worker runs them
    yield
    if sched:
        sched.stop()

log = logging.getLogger('careflow')
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(title='CareFlow API', version='3.0.0', lifespan=lifespan,
                  description='Care-coordination API. All data in demo environments is fictional.',
                  docs_url=None if cfg.env == 'production' else '/api/docs', openapi_url=None if cfg.env == 'production' else '/api/openapi.json')

    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_credentials=True,
                       allow_methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'], allow_headers=['Content-Type', 'X-Requested-With'])

    @app.middleware('http')
    async def csrf_and_headers(request: Request, call_next):
        # CSRF defence in depth (on top of SameSite=Lax cookies): state-changing API calls must carry a custom header,
        # which a cross-site HTML form cannot set and cross-origin fetch cannot send without passing CORS.
        if request.url.path.startswith('/api/') and request.method not in SAFE_METHODS and request.headers.get('x-requested-with') != 'careflow':
            return JSONResponse({'detail': 'Missing X-Requested-With header'}, status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('Referrer-Policy', 'same-origin')
        resp.headers.setdefault('Cache-Control', 'no-store')
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):     # never leak stack traces to clients
        log.exception('Unhandled error on %s %s', request.method, request.url.path)
        return JSONResponse({'detail': 'Internal server error'}, status_code=500)

    for r in (system.router, auth.router, patients.router, patients.referrals_router, appointments.router, diagnostics.router,
              tasks.router, notifications.router, ingest.router, ingest.docs_router, care_gaps.router, care_gaps.jobs_router, dashboard.router, demo.router, assistant.router):
        app.include_router(r)
    return app


app = create_app()
