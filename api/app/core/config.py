"""Application settings, read from environment variables (prefix CAREFLOW_) or an .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='CAREFLOW_', env_file=API_DIR / '.env', extra='ignore')

    env: str = 'development'                     # development | test | production
    # PostgreSQL in production, e.g. postgresql+psycopg://careflow:secret@localhost:5432/careflow
    # SQLite is the zero-install default for local development and tests.
    database_url: str = f"sqlite:///{(API_DIR / 'careflow_dev.db').as_posix()}"

    session_hours: int = 12
    session_cookie: str = 'cf_session'
    cookie_secure: bool = False                  # MUST be true in production (HTTPS only)
    cors_origins: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']

    login_max_failures: int = 5                  # per account within the window → 429
    login_window_minutes: int = 15

    seed_file: Path = API_DIR.parent / 'backend' / 'seed' / 'seed_data.json'

    # Data Import
    upload_dir: Path = API_DIR / 'uploads'       # preserved original files (outside the web root)
    max_upload_bytes: int = 5 * 1024 * 1024
    demo_dir: Path = API_DIR / 'app' / 'ingest' / 'demo_datasets'

    # Background jobs: 'embedded' runs them in the API process (single instance / development);
    # 'off' leaves them to a separate worker (`python -m app.worker`) – use that with several API instances.
    scheduler: str = 'embedded'
    scheduler_interval_seconds: int = 300
    seed_demo_password: str = 'careflow-demo'    # fictional demo accounts only; never used in production

    # LLM (Google Gemini) – words care-gap recommendations. Key comes from the environment / api/.env, never from code.
    llm_enabled: bool = True
    gemini_api_key: str | None = None
    gemini_model: str = 'gemini-3.5-flash'
    # tried in order when the main model is overloaded (503/504), rate-limited (429) or not available to the key (404)
    gemini_fallback_models: list[str] = ['gemini-3.6-flash', 'gemini-3.5-flash-lite']
    llm_timeout_seconds: int = 30
    # The LLM is called only when a person asks for it (on-demand). There is no background wording job.

    @property
    def llm_configured(self) -> bool:
        return self.llm_enabled and bool(self.gemini_api_key)

    # AI agents (app/agents). Kill switch = rollback level L1: CAREFLOW_AGENTS_ENABLED=false turns every agent off and the app
    # behaves like V3.0.0 without AI wording; CAREFLOW_AGENTS_DISABLED='["recommendation"]' turns off individual agents.
    agents_enabled: bool = True
    agents_disabled: list[str] = []
    agent_calls_per_user_per_hour: int = 30      # LLM calls one person may trigger per rolling hour (all agents together)
    agent_cooldown_seconds: int = 60             # pause for everyone after the provider answered 429 on every model (shared key quota)

    # Demo mode: the sign-in screen may reset the database and load a chosen demo scenario. Never in production.
    demo_mode: bool | None = None

    @property
    def demo_enabled(self) -> bool:
        return self.env != 'production' and (self.demo_mode is None or self.demo_mode)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith('sqlite')


@lru_cache
def get_settings() -> Settings:
    return Settings()
