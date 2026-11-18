"""SQLite access: connection factory (foreign keys ON) and controlled, versioned migrations."""
import hashlib, hmac, os, secrets, sqlite3, threading
from datetime import datetime, timezone
from . import config

WRITE_LOCK = threading.RLock()


def connect(path=None):
    p = str(path or config.DB_PATH)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=30, isolation_level=None)  # explicit transactions
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def migrate(conn):
    """Apply any migrations not yet recorded. Never drops or recreates existing data."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for f in sorted(config.MIGRATIONS_DIR.glob("*.sql")):
        if f.stem in done:
            continue
        sql = f.read_text()
        with WRITE_LOCK:
            conn.execute("BEGIN")
            try:
                for stmt in _split_sql(sql):
                    conn.execute(stmt)
                conn.execute("INSERT INTO schema_migrations VALUES (?,?)", (f.stem, now_iso()))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        applied.append(f.stem)
    return applied


def _split_sql(sql):
    """Split a script into statements, keeping CREATE TRIGGER ... END; blocks whole."""
    out, buf, in_trigger = [], [], False
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        if s.upper().startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if s.upper().rstrip(";") .endswith("END"):
                out.append("\n".join(buf)); buf = []; in_trigger = False
        elif s.endswith(";"):
            out.append("\n".join(buf)); buf = []
    if buf:
        out.append("\n".join(buf))
    return out


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def hash_password(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 50_000).hex()
    return f"{salt}${h}"


def check_password(pw, stored):
    try:
        salt, _ = stored.split("$")
    except Exception:
        return False
    return hmac.compare_digest(hash_password(pw, salt), stored)


def next_id(conn, prefix, start=1000):
    row = conn.execute("SELECT value FROM id_sequences WHERE prefix=?", (prefix,)).fetchone()
    v = (row[0] if row else start) + 1
    conn.execute("INSERT INTO id_sequences(prefix,value) VALUES(?,?) ON CONFLICT(prefix) DO UPDATE SET value=excluded.value", (prefix, v))
    return f"{prefix}-{v}"
