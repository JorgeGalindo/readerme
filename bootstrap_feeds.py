#!/usr/bin/env python3
"""One-off: mine Reader history to bootstrap a feeds.json candidate list.

Pulls docs from Reader API (feed + archive), groups by site_name, and
attempts RSS autodiscovery on each site's root domain. Output is curated
manually by the user — this script never overwrites a curated feeds.json.
"""

import json
import os
import pathlib
import re
import time
from collections import defaultdict
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = pathlib.Path(__file__).parent / "data"
FEEDS_FILE = DATA_DIR / "feeds.json"
CANDIDATES_FILE = DATA_DIR / "feeds_candidates.json"

READER_API = "https://readwise.io/api/v3/list/"
TOKEN = os.getenv("READWISE_TOKEN", "")

# Pre-classification: site_name fragments → tag
# These are case-insensitive substrings tested against site_name.
THINKTANK_HINTS = [
    # Spanish
    "elcano", "fedea", "bbva research", "funcas", "esade", "ivie", "ceoe",
    "caixabank research", "banco de españa",
    # Abundance / progress / policy (anglo)
    "niskanen", "institute for progress", "ifp",
    "center for growth and opportunity", "cgo",
    "works in progress", "construction physics", "maximum progress",
    "asterisk", "full stack economics", "fullstackeconomics",
    "mercatus", "brookings", "cato", "aei", "rand", "manhattan institute",
    "abundance institute", "breakthrough institute",
    "progress studies", "roots of progress",
    "centre for policy studies", "policy exchange", "onward",
    "bruegel", "cer", "centre for european reform", "epc",
    "peterson institute", "piie", "cgd", "center for global development",
]

PAPER_HINTS = [
    "nber", "voxeu", "vox eu", "cepr", "sciencedirect",
    "journal of", "american economic review", "quarterly journal of economics",
    "econometrica", "journal of political economy", "review of economic studies",
    "ideas.repec", "repec",
]

COMMON_RSS_PATHS = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss/",
    "/rss.xml",
    "/atom.xml",
    "/feed/atom",
    "/?feed=rss2",
    "/index.xml",
]


def _headers():
    return {"Authorization": f"Token {TOKEN}"}


def _request(url, params):
    for attempt in range(5):
        try:
            r = httpx.get(url, headers=_headers(), params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5))
                print(f"  rate limited, waiting {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout):
            if attempt == 4:
                raise
            time.sleep(2)


def fetch_all(location: str, category: str, max_items: int) -> list[dict]:
    """Page through Reader API for a given location+category."""
    out = []
    cursor = None
    while len(out) < max_items:
        params = {"location": location, "category": category, "page_size": 100}
        if cursor:
            params["pageCursor"] = cursor
        r = _request(READER_API, params)
        data = r.json()
        results = data.get("results", [])
        out.extend(results)
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
        time.sleep(1)
    return out[:max_items]


def normalize_site_name(s: str) -> str:
    return (s or "").strip()


def root_url(source_url: str) -> str:
    """Return scheme://netloc with no path."""
    if not source_url:
        return ""
    p = urlparse(source_url)
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}"


def try_rss(url: str) -> bool:
    """Lightweight check: does URL return XML/RSS-ish content?"""
    try:
        r = httpx.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 readerme-bootstrap"},
            timeout=8,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return False
        ct = r.headers.get("content-type", "").lower()
        body = r.text[:1000].lower()
        is_xml = "xml" in ct or "rss" in ct or "atom" in ct
        looks_rss = "<rss" in body or "<feed" in body or "<rdf:rdf" in body
        return is_xml or looks_rss
    except Exception:
        return False


def autodiscover_rss(root: str) -> str:
    """Try autodiscovery via <link rel=alternate> + common path probes."""
    if not root:
        return ""
    # 1) HTML autodiscovery
    try:
        r = httpx.get(
            root,
            headers={"User-Agent": "Mozilla/5.0 readerme-bootstrap"},
            timeout=10,
            follow_redirects=True,
        )
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for link in soup.find_all("link", rel="alternate"):
                t = (link.get("type") or "").lower()
                if "rss" in t or "atom" in t:
                    href = link.get("href", "")
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = root + href
                    elif not href.startswith("http"):
                        href = root.rstrip("/") + "/" + href
                    if try_rss(href):
                        return href
    except Exception:
        pass

    # 2) Common path probes
    for p in COMMON_RSS_PATHS:
        candidate = root.rstrip("/") + p
        if try_rss(candidate):
            return candidate
    return ""


def classify(site_name: str) -> str:
    s = (site_name or "").lower()
    for hint in PAPER_HINTS:
        if hint in s:
            return "papers"
    for hint in THINKTANK_HINTS:
        if hint in s:
            return "thinktank"
    return "main"


def main():
    if not TOKEN:
        print("ERROR: READWISE_TOKEN missing in env")
        return

    print("Fetching Reader feed (current unseen)…")
    feed_docs = []
    for cat in ("rss", "email"):
        feed_docs.extend(fetch_all("feed", cat, max_items=2000))
    print(f"  got {len(feed_docs)} from feed")

    print("Fetching Reader archive (history)…")
    archive_docs = []
    for cat in ("rss", "email"):
        archive_docs.extend(fetch_all("archive", cat, max_items=2000))
    print(f"  got {len(archive_docs)} from archive")

    all_docs = feed_docs + archive_docs
    print(f"Total docs: {len(all_docs)}")

    # Group by site_name
    by_site = defaultdict(lambda: {"count": 0, "sample_url": "", "last_seen": ""})
    for d in all_docs:
        site = normalize_site_name(d.get("site_name"))
        if not site:
            # Fallback: use domain as site key
            url = d.get("source_url", "")
            site = re.sub(r"^www\.", "", urlparse(url).netloc) if url else ""
        if not site:
            continue
        rec = by_site[site]
        rec["count"] += 1
        url = d.get("source_url") or ""
        if url and not rec["sample_url"]:
            rec["sample_url"] = url
        ts = d.get("updated_at") or d.get("created_at") or ""
        if ts > rec["last_seen"]:
            rec["last_seen"] = ts

    sites = sorted(
        ((name, r) for name, r in by_site.items()),
        key=lambda x: x[1]["count"],
        reverse=True,
    )
    print(f"Unique sites: {len(sites)}")

    # Autodiscover RSS for each (skip if too few docs to be worth it)
    candidates = []
    for i, (name, r) in enumerate(sites):
        root = root_url(r["sample_url"])
        rss_url = ""
        if root and r["count"] >= 1:
            rss_url = autodiscover_rss(root)
        tag = classify(name)
        candidates.append({
            "site_name": name,
            "rss_url": rss_url,
            "root_url": root,
            "count": r["count"],
            "last_seen": r["last_seen"],
            "sample_url": r["sample_url"],
            "tag_suggested": tag,
            "tag": "",  # user fills this
        })
        if (i + 1) % 20 == 0:
            print(f"  processed {i + 1}/{len(sites)}")

    DATA_DIR.mkdir(exist_ok=True)
    CANDIDATES_FILE.write_text(json.dumps(candidates, ensure_ascii=False, indent=2))
    print(f"\nWrote {CANDIDATES_FILE} with {len(candidates)} entries.")
    print("Next: review feeds_candidates.json, set 'tag' to main/thinktank/papers/skip,")
    print("then save as feeds.json.")

    # Quick stats
    with_rss = sum(1 for c in candidates if c["rss_url"])
    print(f"\nStats: {with_rss}/{len(candidates)} sites with discovered RSS")
    by_tag = defaultdict(int)
    for c in candidates:
        by_tag[c["tag_suggested"]] += 1
    for t, n in sorted(by_tag.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
