"""Storage adapter: filesystem in dev, Vercel Blob in prod.

Public API:
    read_json(name) -> dict | list | None
    write_json(name, obj) -> None
    read_bytes(name) -> bytes | None
    write_bytes(name, data, content_type="application/octet-stream") -> None
    exists(name) -> bool

Backend selection:
    If BLOB_READ_WRITE_TOKEN is set in the environment → Vercel Blob.
    Otherwise → local data/ directory next to this file.

Names are bare filenames like "main.json" or "briefing_main.mp3"; the adapter
prefixes them with the right path/prefix per backend.

Read fallback in Blob mode: if a name isn't in Blob yet (e.g. config files
like feeds.json that ship with the deploy), we fall through to the local
filesystem. This lets feeds.json/profile.json live in git and the rest of
data/ live in Blob without code branching everywhere.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

import httpx

DATA_DIR = pathlib.Path(__file__).parent / "data"
BLOB_PREFIX = "readerme/"  # all blobs live under this folder in the store


def _blob_token() -> str | None:
    return os.environ.get("BLOB_READ_WRITE_TOKEN")


def _blob_enabled() -> bool:
    return bool(_blob_token())


# ---------- local filesystem backend ----------

def _local_path(name: str) -> pathlib.Path:
    return DATA_DIR / name


def _local_read_bytes(name: str) -> bytes | None:
    p = _local_path(name)
    if not p.exists():
        return None
    return p.read_bytes()


def _local_write_bytes(name: str, data: bytes) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    _local_path(name).write_bytes(data)


def _local_exists(name: str) -> bool:
    return _local_path(name).exists()


# ---------- Vercel Blob backend ----------
# Docs: https://vercel.com/docs/storage/vercel-blob/using-blob-sdk
# REST API used directly to keep the dependency surface minimal.

_BLOB_API = "https://blob.vercel-storage.com"
_blob_url_cache: dict[str, str] = {}  # name -> public URL


def _blob_key(name: str) -> str:
    return f"{BLOB_PREFIX}{name}"


def _blob_list() -> dict[str, str]:
    """List all blobs under our prefix. Returns {pathname: public_url}."""
    token = _blob_token()
    if not token:
        return {}
    out: dict[str, str] = {}
    cursor = None
    while True:
        params = {"prefix": BLOB_PREFIX, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        r = httpx.get(_BLOB_API, params=params,
                      headers={"authorization": f"Bearer {token}"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        for b in data.get("blobs", []):
            out[b["pathname"]] = b["url"]
        cursor = data.get("cursor")
        if not cursor:
            break
    return out


def _blob_url(name: str) -> str | None:
    """Resolve a blob name to its public URL. Caches the listing."""
    if not _blob_url_cache:
        _blob_url_cache.update(_blob_list())
    return _blob_url_cache.get(_blob_key(name))


def _blob_invalidate(name: str) -> None:
    _blob_url_cache.pop(_blob_key(name), None)


def _blob_read_bytes(name: str) -> bytes | None:
    url = _blob_url(name)
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def _blob_write_bytes(name: str, data: bytes, content_type: str) -> None:
    token = _blob_token()
    if not token:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN not set")
    key = _blob_key(name)
    # `addRandomSuffix=false` so we can reach the blob by stable path.
    # `allowOverwrite=true` so re-uploads replace the existing blob.
    r = httpx.put(
        f"{_BLOB_API}/{key}",
        params={"addRandomSuffix": "false", "allowOverwrite": "true"},
        headers={
            "authorization": f"Bearer {token}",
            "x-content-type": content_type,
            "x-api-version": "7",
        },
        content=data,
        timeout=60,
    )
    r.raise_for_status()
    body = r.json()
    _blob_url_cache[key] = body["url"]


def _blob_exists(name: str) -> bool:
    return _blob_url(name) is not None


# ---------- public API ----------

def read_bytes(name: str) -> bytes | None:
    """Read raw bytes. Tries Blob first if enabled, then falls back to local."""
    if _blob_enabled():
        b = _blob_read_bytes(name)
        if b is not None:
            return b
    return _local_read_bytes(name)


def write_bytes(name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Write raw bytes. Goes to Blob if enabled, else local."""
    if _blob_enabled():
        _blob_write_bytes(name, data, content_type)
    else:
        _local_write_bytes(name, data)


def read_json(name: str) -> Any:
    """Read JSON. Returns None if not found."""
    raw = read_bytes(name)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def write_json(name: str, obj: Any) -> None:
    """Write JSON (utf-8, indent=2)."""
    data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    write_bytes(name, data, content_type="application/json")


def exists(name: str) -> bool:
    """Check existence in Blob (if enabled) or local."""
    if _blob_enabled() and _blob_exists(name):
        return True
    return _local_exists(name)


def public_url(name: str) -> str | None:
    """Public URL for direct download (e.g. mp3 redirects). None if not in Blob."""
    if _blob_enabled():
        return _blob_url(name)
    return None


def refresh_blob_cache() -> None:
    """Force a re-list. Useful after a write from another process."""
    _blob_url_cache.clear()
