"""Bupa CareFlow V2 backend – stdlib HTTP server + SQLite. Run:  python3 -m backend.server"""
import base64, hashlib, json, mimetypes, re, secrets, sys, traceback
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import config, db, mapping, priority, seed


class ApiError(Exception):
    def __init__(self, msg, status=400, extra=None):
        super().__init__(msg); self.status = status; self.extra = extra or {}


def utc_in(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S.000Z')


class Handler(BaseHTTPRequestHandler):
    server_version = 'CareFlowV2/1.0'

    def log_message(self, fmt, *a):
        if '--quiet' not in sys.argv:
            sys.stderr.write('%s %s\n' % (self.command, self.path))

    # ---- helpers
    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > config.MAX_UPLOAD_BYTES * 2 + 1_000_000:
            raise ApiError('Request too large', 413)
        raw = self.rfile.read(n) if n else b'{}'
        try:
            return json.loads(raw or b'{}')
        except Exception:
            raise ApiError('Invalid JSON body')

    def _user(self, conn, required=True):
        h = self.headers.get('Authorization', '')
        tok = h[7:] if h.startswith('Bearer ') else ''
        if tok:
            r = conn.execute("SELECT u.id,u.name,u.role,u.title,u.active,s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
                             (hashlib.sha256(tok.encode()).hexdigest(),)).fetchone()
            if r and r['active'] and r['expires_at'] > db.now_iso():
                return dict(id=r['id'], name=r['name'], role=r['role'], title=r['title'])
        if required:
            raise ApiError('Authentication required', 401)
        return None

    def _dispatch(self, method):
        path = urlparse(self.path).path
        conn = db.connect()
        try:
            if method == 'GET' and not path.startswith('/api/'):
                return self._static(path)
            routes = ROUTES.get(method, [])
            for pat, fn in routes:
                m = pat.fullmatch(path)
                if m:
                    res = fn(self, conn, *m.groups())
                    if res is not None:
                        self._json(200, res)
                    return
            raise ApiError('Not found', 404)
        except ApiError as e:
            self._json(e.status, {'error': str(e), **e.extra})
        except priority.PriorityError as e:
            self._json(e.status, {'error': str(e)})
        except Exception as e:  # never leak a stack trace to the client
            traceback.print_exc()
            self._json(500, {'error': 'Server error: ' + str(e)})
        finally:
            conn.close()

    def do_GET(self): self._dispatch('GET')
    def do_POST(self): self._dispatch('POST')
    def do_PATCH(self): self._dispatch('PATCH')

    def _static(self, path):
        if path == '/favicon.ico':
            self.send_response(204); self.end_headers(); return
        if path in ('', '/'):
            path = '/index.html'
        f = (config.FRONTEND_DIR / path.lstrip('/')).resolve()
        if config.FRONTEND_DIR.resolve() not in f.parents and f != config.FRONTEND_DIR.resolve() or not f.is_file():
            raise ApiError('Not found', 404)
        data = f.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', (mimetypes.guess_type(str(f))[0] or 'application/octet-stream') + ('; charset=utf-8' if f.suffix in ('.html', '.js', '.css') else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(data)


# ================================================================== routes
def r_health(h, conn):
    n = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    mig = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    return {'ok': True, 'db': str(config.DB_PATH), 'patients': n, 'migrations': mig, 'foreignKeys': conn.execute("PRAGMA foreign_keys").fetchone()[0]}


def r_login(h, conn):
    b = h._body()
    u = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (b.get('userId'),)).fetchone()
    if not u or not db.check_password(b.get('password') or '', u['password_hash'] or ''):
        raise ApiError('Incorrect user or password', 401)
    tok = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions VALUES(?,?,?,?)", (hashlib.sha256(tok.encode()).hexdigest(), u['id'], db.now_iso(), utc_in(config.SESSION_HOURS)))
    return {'token': tok, 'user': {'id': u['id'], 'name': u['name'], 'role': u['role'], 'title': u['title']}}


def r_logout(h, conn):
    t = h.headers.get('Authorization', '')[7:]
    if t:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(t.encode()).hexdigest(),))
    return {'ok': True}


def r_me(h, conn):
    return {'user': h._user(conn)}


def r_users_public(h, conn):  # for the login screen (names only)
    return {'users': [dict(id=r['id'], name=r['name'], role=r['role'], title=r['title'], email=r['email']) for r in conn.execute("SELECT id,name,role,title,email FROM users WHERE active=1 ORDER BY rowid")]}


def r_state(h, conn):
    h._user(conn)
    return mapping.load_state(conn)


def r_sync(h, conn):
    u = h._user(conn)
    ch = h._body().get('changes') or {}
    try:
        rep = mapping.apply_changes(conn, ch, u)
    except Exception as e:
        raise ApiError('Database rejected the change: ' + str(e), 409)
    return rep


def r_priority_change(h, conn):
    u = h._user(conn)
    b = h._body()
    return {'entry': priority.change_priority(conn, u, b.get('patientId'), b.get('newPriority'), b.get('comment'))}


def r_priority_history(h, conn, pid):
    u = h._user(conn)
    rows = conn.execute("SELECT * FROM priority_history WHERE patient_id=? ORDER BY id", (pid,)).fetchall()
    return {'history': [dict(r) for r in rows]}


def r_reset_guard(h, conn):
    raise ApiError('Database reset is not available. V2 never recreates its database on start.', 403)


# ingestion routes are provided by ingest_api (registered below)
ROUTES = {'GET': [], 'POST': [], 'PATCH': []}


def route(method, pattern, fn):
    ROUTES[method].append((re.compile(pattern), fn))


route('GET', r'/api/health', r_health)
route('POST', r'/api/login', r_login)
route('POST', r'/api/logout', r_logout)
route('GET', r'/api/me', r_me)
route('GET', r'/api/users/public', r_users_public)
route('GET', r'/api/state', r_state)
route('POST', r'/api/sync', r_sync)
route('POST', r'/api/priority', r_priority_change)
route('GET', r'/api/priority/([A-Za-z0-9_-]+)', r_priority_history)
route('POST', r'/api/admin/reset', r_reset_guard)

from . import ingest_api  # noqa: E402  (registers /api/ingest/* routes)
ingest_api.register(route, ApiError)


def init_db():
    conn = db.connect()
    applied = db.migrate(conn)
    seeded = seed.seed_if_empty(conn)
    conn.close()
    return applied, bool(seeded)


def main():
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    applied, seeded = init_db()
    print(f"[CareFlow V2] database: {config.DB_PATH}")
    print(f"[CareFlow V2] migrations applied now: {applied or 'none (already up to date)'}; seeded now: {seeded}")
    srv = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print(f"[CareFlow V2] http://{config.HOST}:{config.PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
