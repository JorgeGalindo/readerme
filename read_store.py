"""Persistent ledger of "read" items.

In production: Upstash Redis (Vercel KV / Marketplace), accessed via REST.
Items live in a single Redis Hash `readerme:read` (field = normalized URL,
value = ISO timestamp). Hash gives us O(1) lookup and a single GET to load
the full ledger for filter_unread.

In local dev (no KV env vars): falls back to data/read.json so `python run.py`
keeps working without any Vercel setup.

URL normalization mirrors normUrl in static/read.js so server- and
client-side keys match.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlparse, parse_qsl, urlencode, quote

import httpx
from local_files import atomic_write

DATA_DIR = pathlib.Path(__file__).parent / "data"
READ_FILE = DATA_DIR / "read.json"

KV_HASH_KEY = "readerme:read"

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
        path = quote(re.sub(r"/+$", "", u.path) or "/", safe="/%:@!$&'()*+,;=-._~")
        host = (u.hostname or "").lower()
        host = f"[{host}]" if ":" in host else host.encode("idna").decode("ascii")
        if u.port is not None and (u.scheme, u.port) not in (("http", 80), ("https", 443)):
            host += f":{u.port}"
        query = ("?" + urlencode(q)) if q else ""
        return f"{u.scheme}://{host}{path}{query}"
    except Exception:
        return raw.strip().lower()


# ---------- backend selection ----------

def _kv_url() -> str | None:
    return os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")


def _kv_token() -> str | None:
    return os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")


def _kv_enabled() -> bool:
    return bool(_kv_url() and _kv_token())


def _kv_call(command: list) -> any:
    """POST a single Redis command to Upstash REST. Returns the `result` field."""
    url = _kv_url()
    token = _kv_token()
    r = httpx.post(url, headers={"authorization": f"Bearer {token}"},
                   json=command, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict) or "result" not in body:
        raise RuntimeError("Invalid KV response")
    if "error" in body:
        raise RuntimeError(f"KV error: {body['error']}")
    return body.get("result")


# ---------- KV-backed ops ----------

def _kv_load() -> dict:
    result = _kv_call(["HGETALL", KV_HASH_KEY])
    # Upstash returns either a flat list [k1, v1, k2, v2, ...] or a dict.
    if isinstance(result, dict):
        return dict(result)
    if isinstance(result, list):
        return {result[i]: result[i + 1] for i in range(0, len(result), 2)}
    return {}


def _kv_mark(url_norm: str, ts: str) -> None:
    result = _kv_call(["HSET", KV_HASH_KEY, url_norm, ts])
    if type(result) is not int or result not in (0, 1):
        raise RuntimeError("KV did not confirm the read mark")


def _kv_clear() -> None:
    result = _kv_call(["DEL", KV_HASH_KEY])
    if type(result) is not int or result not in (0, 1):
        raise RuntimeError("KV did not confirm the ledger reset")


# ---------- local-file ops (dev fallback) ----------

def _local_load() -> dict:
    if not READ_FILE.exists():
        return {}
    try:
        return json.loads(READ_FILE.read_text())
    except Exception:
        return {}


def _local_save(state: dict) -> None:
    atomic_write(READ_FILE, json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))


# ---------- public API ----------

def load() -> dict:
    state = None
    if _kv_enabled():
        try:
            state = _kv_load()
        except Exception as e:
            print(f"  [read_store] KV load failed, falling back to local: {e}")
    if state is None:
        state = _local_load()
    if not isinstance(state, dict):
        return {}
    return {norm_url(url): ts for url, ts in state.items()}


def mark(url: str) -> None:
    n = norm_url(url)
    if not n:
        return
    ts = datetime.now(timezone.utc).isoformat()
    if _kv_enabled():
        # A local file in a serverless instance is not a durable fallback.
        # Let the client retain the pending mark and retry the configured store.
        _kv_mark(n, ts)
        return
    with _lock:
        state = _local_load()
        state[n] = ts
        _local_save(state)


def clear() -> None:
    if _kv_enabled():
        _kv_clear()
        return
    with _lock:
        _local_save({})


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
