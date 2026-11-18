"""Method A: preloaded synthetic data. Idempotent – seeds ONLY an empty database and never resets it."""
import json, re
from datetime import date, datetime, timedelta
from . import config, db, mapping

DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(.*)$")


def _shift(o, days):
    if isinstance(o, str):
        m = DATE_RE.match(o)
        if m and days:
            d = date(int(m[1]), int(m[2]), int(m[3])) + timedelta(days=days)
            return d.isoformat() + m[4]
        return o
    if isinstance(o, list):
        return [_shift(x, days) for x in o]
    if isinstance(o, dict):
        return {k: _shift(v, days) for k, v in o.items()}
    return o


def is_seeded(conn):
    return conn.execute("SELECT 1 FROM app_settings WHERE key='seeded_on'").fetchone() is not None


def seed_if_empty(conn, force_demo_dates=True):
    if is_seeded(conn):
        return False
    raw = json.loads(config.SEED_FILE.read_text())
    delta = (date.today() - date.fromisoformat(raw['seededOn'])).days   # keep scenarios relative to "today"
    S = _shift(raw, delta)
    initial = {p['id']: p.get('priority', 'med') for p in S['patients']}
    changes = {c: {'upsert': S[c]} for c in mapping.ORDER}
    changes['blobs'] = {n: {'upsert': (S[n] if isinstance(S[n], dict) else {x['id']: x for x in S[n]})} for n in mapping.BLOBS}
    changes['seq'] = S['seq']
    changes['settings'] = S['settings']
    for name in S['settings'].get('depts', {}):
        conn.execute("INSERT OR IGNORE INTO departments(name, enabled) VALUES(?,1)", (name,))
    # users first with a system actor
    actor = {'id': None, 'name': 'System (seed)', 'role': 'system'}
    ctx = {'initial_priority': initial, 'initial_comment': 'Initial priority assigned when synthetic demo data was loaded'}
    rep = mapping.apply_changes(conn, changes, actor, ctx)
    conn.execute("INSERT INTO app_settings(key,value_json) VALUES('seeded_on',?)", (json.dumps(date.today().isoformat()),))
    return rep


if __name__ == '__main__':
    c = db.connect(); db.migrate(c)
    print('seeded' if seed_if_empty(c) else 'already seeded – nothing changed')
