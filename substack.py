"""Route Substack posts through open.substack.com so iOS opens the app.

A Universal Link needs both halves of a handshake: the domain must declare the
app (its apple-app-site-association file) *and* the app must declare the domain
(its Associated Domains entitlement, a fixed list compiled into the binary).

Substack serves the AASA on every custom domain — noahpinion.blog and friends
all point at 7DGN24C3GR.com.substack.Substack — but the app can only claim its
own domains, not the hundreds of thousands its publications use. So the domain
says "I belong to Substack" and the app answers "I don't know you": tapping
noahpinion.blog/p/... never leaves the browser.

open.substack.com claims paths ["*"], so the canonical app link is

    https://open.substack.com/pub/<publication>/p/<slug>

which opens the app when installed and falls back to the web post when not.
Posts already on *.substack.com are left alone: the app claims that wildcard,
so they work directly and need no extra redirect hop.

The publication id normally comes free from the feed's <webMaster>
(noahpinion@substack.com -> noahpinion). A handful of feeds put a real contact
address there instead; for those we read the id off a post page once and cache
it in substack_pubs.json.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

import storage

CACHE_NAME = "substack_pubs.json"
OPEN_HOST = "https://open.substack.com"

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}

# open.substack.com/pub/<publication>/ as it appears in a rendered post page.
_PUB_IN_PAGE = re.compile(r"open\.substack\.com/pub/([a-z0-9][a-z0-9-]*)/", re.I)
_POST_PATH = re.compile(r"^/p/([^/]+)/?$")

_cache: dict[str, str] | None = None


def _load_cache() -> dict[str, str]:
    global _cache
    if _cache is None:
        _cache = storage.read_json(CACHE_NAME) or {}
    return _cache


def _save_cache(cache: dict[str, str]) -> None:
    global _cache
    _cache = cache
    storage.write_json(CACHE_NAME, cache)


def is_substack(soup) -> bool:
    """True if the parsed feed declares <generator>Substack</generator>."""
    gen = soup.find("generator")
    return bool(gen and gen.text and gen.text.strip().lower() == "substack")


def pub_from_webmaster(soup) -> str | None:
    """Read the publication id off <webMaster>noahpinion@substack.com</webMaster>."""
    for tag in ("webMaster", "email"):
        el = soup.find(tag)
        if el and el.text and el.text.strip().endswith("@substack.com"):
            pub = el.text.strip().split("@")[0].strip()
            if pub:
                return pub
    return None


def _pub_from_post_page(post_url: str) -> str | None:
    """Fallback: rendered post pages carry their own open.substack.com link."""
    try:
        r = httpx.get(post_url, headers=_UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        print(f"  [substack] could not read {post_url}: {e}")
        return None
    m = _PUB_IN_PAGE.search(r.text)
    return m.group(1) if m else None


def resolve_pub(rss_url: str, soup, sample_post_url: str = "") -> str | None:
    """Publication id for a feed, cached across runs. None if undeterminable."""
    cache = _load_cache()
    if rss_url in cache:
        return cache[rss_url] or None

    pub = pub_from_webmaster(soup)
    if not pub and sample_post_url:
        pub = _pub_from_post_page(sample_post_url)
        if pub:
            print(f"  [substack] resolved '{pub}' from post page for {rss_url}")

    # Cache negatives too ("") so a stubborn feed isn't refetched every night.
    cache[rss_url] = pub or ""
    _save_cache(cache)
    return pub


def app_url(post_url: str, pub: str) -> str | None:
    """Rewrite a custom-domain post URL to its open.substack.com equivalent.

    Returns None when there is nothing to do: no publication id, not a /p/<slug>
    post, or already on a substack.com host (the app claims those directly).
    """
    if not post_url or not pub:
        return None
    try:
        u = urlparse(post_url)
    except Exception:
        return None
    host = (u.hostname or "").lower()
    if not host or host == "substack.com" or host.endswith(".substack.com"):
        return None
    m = _POST_PATH.match(u.path or "")
    if not m:
        return None
    return f"{OPEN_HOST}/pub/{pub}/p/{m.group(1)}"
