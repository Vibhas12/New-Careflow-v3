"""Demo dataset templates → concrete CSV bytes. Date tokens are relative to the load day: {T}, {T+7}, {T-8}."""
import re
from datetime import date, timedelta

TOKEN = re.compile(r'\{T(?:([+-])(\d{1,4}))?\}')


def today_iso():
    return date.today().isoformat()


def render(path, today=None):
    base = today or date.today()

    def sub(m):
        n = int(m[2] or 0) * (-1 if m[1] == '-' else 1)
        return (base + timedelta(days=n)).isoformat()
    return TOKEN.sub(sub, path.read_text(encoding='utf-8')).encode('utf-8')


def filename(ds):
    # the date makes re-loading on the same day an exact-file duplicate (detected by SHA-256), but a fresh load on another day is allowed
    return f"demo_{ds['file'][:-4]}_{today_iso()}.csv"
