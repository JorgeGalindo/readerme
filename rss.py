"""RSS engine: fetch tagged feeds from feeds.json, return items new since last run.

State (rss_state.json) is one entry per rss_url with the latest seen item id
(GUID or link, whichever the feed exposes). On each run we walk the feed top-down
and stop at the first item whose id is in state — everything above is new.
"""

import hashlib
import json
import pathlib
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

DATA_DIR = pathlib.Path(__file__).parent / "data"
FEEDS_FILE = DATA_DIR / "feeds.json"
STATE_FILE = DATA_DIR / "rss_state.json"

UA = "Mozilla/5.0 (compatible; readerme/1.0; +https://github.com/JorgeGalindo/readerme)"


def _load_feeds() -> list[dict]:
    if not FEEDS_FILE.exists():
        return []
    return json.loads(FEEDS_FILE.read_text())


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())


def _save_state(state: dict):
    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _stable_id(item_url: str, guid: str) -> str:
    """Stable id per item: prefer GUID, fall back to URL hash."""
    if guid:
        return guid.strip()
    if item_url:
        return hashlib.sha1(item_url.encode()).hexdigest()
    return ""


def _parse_date(raw: str) -> str:
    """Best-effort: convert various RSS/Atom date formats to ISO 8601."""
    if not raw:
        return ""
    raw = raw.strip()
    # RFC 822 (RSS pubDate)
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
    except (TypeError, ValueError):
        pass
    # ISO 8601 (Atom updated/published)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return ""


def _strip_html(html: str, max_len: int = 400) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return text[:max_len]


def _parse_feed(xml_text: str, site_name: str, rss_url: str) -> list[dict]:
    """Parse RSS or Atom into a normalized article list (newest first)."""
    soup = BeautifulSoup(xml_text, "xml")

    items = soup.find_all("item")
    is_atom = False
    if not items:
        items = soup.find_all("entry")
        is_atom = True

    articles = []
    for it in items:
        title_el = it.find("title")
        title = title_el.text.strip() if title_el else ""
        if not title:
            continue

        # URL
        if is_atom:
            link_el = it.find("link", rel="alternate") or it.find("link")
            url = (link_el.get("href") if link_el else "") or ""
        else:
            link_el = it.find("link")
            url = link_el.text.strip() if link_el else ""

        # GUID / id
        guid_el = it.find("guid") or it.find("id")
        guid = guid_el.text.strip() if guid_el else ""

        # Date
        date_raw = ""
        for tag in ("pubDate", "published", "updated", "dc:date"):
            el = it.find(tag)
            if el and el.text:
                date_raw = el.text
                break
        published_iso = _parse_date(date_raw)

        # Summary
        summary_html = ""
        for tag in ("description", "summary", "content:encoded", "content"):
            el = it.find(tag)
            if el and el.text:
                summary_html = el.text
                break
        summary = _strip_html(summary_html)

        # Author
        author = ""
        author_el = it.find("author") or it.find("dc:creator")
        if author_el:
            if author_el.find("name"):
                author = author_el.find("name").text.strip()
            else:
                author = author_el.text.strip()

        articles.append({
            "id": _stable_id(url, guid),
            "title": title,
            "source_url": url,
            "site_name": site_name,
            "summary": summary,
            "author": author,
            "published_date": published_iso,
            "_feed": rss_url,
        })

    return articles


def _fetch_one(rss_url: str, site_name: str, last_seen_id: Optional[str]) -> tuple[list[dict], str]:
    """Fetch and parse one feed. Returns (new_items, new_last_seen_id).

    new_items = articles encountered before hitting last_seen_id (i.e., everything
    new since the previous run). If last_seen_id is None or not found, returns all
    items (first run for this feed).
    """
    try:
        r = httpx.get(rss_url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        print(f"  [skip] {site_name}: {e}")
        return [], last_seen_id or ""

    try:
        articles = _parse_feed(r.text, site_name, rss_url)
    except Exception as e:
        print(f"  [parse-error] {site_name}: {e}")
        return [], last_seen_id or ""

    if not articles:
        return [], last_seen_id or ""

    new_top_id = articles[0]["id"]

    # First run for this feed: take everything
    if not last_seen_id:
        return articles, new_top_id

    # Walk until we hit last_seen_id
    new_items = []
    for a in articles:
        if a["id"] == last_seen_id:
            break
        new_items.append(a)

    return new_items, new_top_id


def fetch_by_tag(tag: str, sleep_between: float = 0.3) -> list[dict]:
    """Fetch all feeds with the given tag, return new items since last run.

    Updates rss_state.json so the next run only picks up what's new.
    """
    feeds = [f for f in _load_feeds() if f.get("tag") == tag]
    state = _load_state()

    all_new = []
    for f in feeds:
        rss_url = f["rss_url"]
        site = f.get("site_name") or rss_url
        last = state.get(rss_url)
        new_items, new_top = _fetch_one(rss_url, site, last)
        if new_items:
            print(f"  [{site}] {len(new_items)} new")
        if new_top:
            state[rss_url] = new_top
        all_new.extend(new_items)
        time.sleep(sleep_between)

    _save_state(state)
    return all_new


if __name__ == "__main__":
    items = fetch_by_tag("main")
    print(f"\nTotal new items (main): {len(items)}")
    for a in items[:5]:
        print(f"  [{a['site_name']}] {a['title']}")
