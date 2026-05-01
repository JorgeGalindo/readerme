"""Persistent ledger of "read" items, deployment-wide.

Items marked via POST /api/read land in data/read.json (committed by the
nightly workflow) and are filtered out of all list outputs (curators +
renders). Wiped via POST /api/read/clear.

URL normalization mirrors the JS _normUrl in templates so server- and
client-side keys match.
"""

import json
import pathlib
import re
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlparse, parse_qsl, urlencode

DATA_DIR = pathlib.Path(__file__).parent / "data"
READ_FILE = DATA_DIR / "read.json"

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_cid|mc_eid|ref_|ref$|_hsenc|_hsmi)", re.I)
_lock = Lock()


def norm_url(raw: str) -> str:
    if not raw:
        return ""
    try:
        u = urlparse(raw.strip())
        if not u.scheme or not u.netloc:
            return raw.strip().lower()
        q = sorted([(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                    if not _TRACKING.match(k)])
        path = re.sub(r"/+$", "", u.path) or "/"
        host = (u.hostname or "").lower()
        query = ("?" + urlencode(q)) if q else ""
        return f"{u.scheme}://{host}{path}{query}"
    except Exception:
        return raw.strip().lower()


def load() -> dict:
    if not READ_FILE.exists():
        return {}
    try:
        return json.loads(READ_FILE.read_text())
    except Exception:
        return {}


def save(state: dict):
    DATA_DIR.mkdir(exist_ok=True)
    READ_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def mark(url: str):
    n = norm_url(url)
    if not n:
        return
    with _lock:
        state = load()
        state[n] = datetime.now(timezone.utc).isoformat()
        save(state)


def clear():
    with _lock:
        save({})


def is_read(url: str, state: dict | None = None) -> bool:
    if state is None:
        state = load()
    return norm_url(url) in state


def filter_unread(items: list[dict], url_keys: tuple[str, ...] = ("source_url", "url")) -> list[dict]:
    state = load()
    if not state:
        return items
    out = []
    for a in items:
        url = ""
        for k in url_keys:
            if a.get(k):
                url = a[k]
                break
        if norm_url(url) not in state:
            out.append(a)
    return out
