"""Bupa CareFlow V2 configuration. Separate from V1 (V1 has no backend and no database file)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CAREFLOW_V2_DB", ROOT / "database" / "careflow_v2.db"))
UPLOAD_DIR = Path(os.environ.get("CAREFLOW_V2_UPLOADS", ROOT / "uploads"))
MIGRATIONS_DIR = ROOT / "migrations"
SEED_FILE = ROOT / "seed" / "seed_data.json"
DEMO_DIR = ROOT / "demo_datasets"   # one-click demo CSVs for the Data Import screen
FRONTEND_DIR = ROOT.parent / "frontend" / "dist"
HOST = os.environ.get("CAREFLOW_V2_HOST", "127.0.0.1")
PORT = int(os.environ.get("CAREFLOW_V2_PORT", "8787"))
MAX_UPLOAD_BYTES = int(os.environ.get("CAREFLOW_V2_MAX_UPLOAD", 5 * 1024 * 1024))
ALLOWED_UPLOAD_TYPES = {"csv", "json", "pdf"}
SESSION_HOURS = 12
DEMO_PASSWORD = "careflow-demo"   # fictional demo accounts only
