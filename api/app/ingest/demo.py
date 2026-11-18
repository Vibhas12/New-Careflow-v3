"""One-click demo datasets: CSV templates whose dates are relative to the load day ({T}, {T+7}, {T-8})."""
import json
import re
from datetime import date, timedelta

from app.core.config import get_settings

TOKEN = re.compile(r'\{T(?:([+-])(\d{1,4}))?\}')


def manifest() -> list[dict]:
    try:
        return json.loads((get_settings().demo_dir / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []


def find(dataset_id: str) -> dict | None:
    return next((m for m in manifest() if m['id'] == dataset_id), None)


def render(ds: dict, base: date | None = None) -> bytes:
    base = base or date.today()

    def sub(m):
        n = int(m[2] or 0) * (-1 if m[1] == '-' else 1)
        return (base + timedelta(days=n)).isoformat()
    return TOKEN.sub(sub, (get_settings().demo_dir / ds['file']).read_text(encoding='utf-8')).encode('utf-8')


def filename(ds: dict) -> str:
    # the date makes a same-day reload an exact-file duplicate (SHA-256), while a load on another day is allowed
    return f"demo_{ds['file'][:-4]}_{date.today().isoformat()}.csv"
