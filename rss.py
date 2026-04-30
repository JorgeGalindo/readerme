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

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
HTTP_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, text/html;q=0.7, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
}


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
        r = httpx.get(rss_url, headers=HTTP_HEADERS, timeout=20, follow_redirects=True)
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


def _fetch_articles(feed: dict) -> list[dict]:
    """Dispatch by feed_type. Default 'rss' parses RSS/Atom; custom types route
    to dedicated handlers (sitemap, scrape) for sites that don't expose feeds."""
    rss_url = feed["rss_url"]
    site = feed.get("site_name") or rss_url
    feed_type = feed.get("feed_type", "rss")

    if feed_type == "sitemap_tbi":
        return _fetch_tbi_sitemap(rss_url, site)
    if feed_type == "scrape_epc":
        return _fetch_epc_scrape(rss_url, site)

    try:
        r = httpx.get(rss_url, headers=HTTP_HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return _parse_feed(r.text, site, rss_url)
    except Exception as e:
        print(f"  [skip] {site}: {e}")
        return []


def fetch_latest_by_tag(tag: str, max_per_feed: int = 10, sleep_between: float = 0.3) -> list[dict]:
    """Fetch the latest N items from each feed with the given tag, ignoring state.

    Used by sections like Thinktanks where we always want the freshest items
    rather than only deltas-since-last-run. Each item carries the feed's `subtag`
    if defined in feeds.json.
    """
    feeds = [f for f in _load_feeds() if f.get("tag") == tag]
    out = []
    for f in feeds:
        subtag = f.get("subtag", "")
        articles = _fetch_articles(f)
        for a in articles[:max_per_feed]:
            a["subtag"] = subtag
            out.append(a)
        time.sleep(sleep_between)
    return out


def _fetch_tbi_sitemap(sitemap_url: str, site_name: str, max_items: int = 25) -> list[dict]:
    """Tony Blair Institute exposes no RSS but does publish a sitemap with
    `lastmod` for every /insights/ page. We sort by lastmod desc and take the
    most recent N. Title is fetched per-page (one extra request each)."""
    try:
        r = httpx.get(sitemap_url, headers=HTTP_HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "xml")
    except Exception as e:
        print(f"  [skip] {site_name}: sitemap fetch failed: {e}")
        return []

    insights = []
    for u in soup.find_all("url"):
        loc_el = u.find("loc")
        lastmod_el = u.find("lastmod")
        if not loc_el or "/insights/" not in loc_el.text:
            continue
        insights.append((loc_el.text, lastmod_el.text if lastmod_el else ""))

    insights.sort(key=lambda x: x[1], reverse=True)
    out = []
    for url, lastmod in insights[:max_items]:
        title = ""
        try:
            pr = httpx.get(url, headers=HTTP_HEADERS, timeout=15, follow_redirects=True)
            if pr.status_code == 200:
                psoup = BeautifulSoup(pr.text, "html.parser")
                t_el = psoup.find("meta", property="og:title") or psoup.find("title")
                if t_el:
                    title = t_el.get("content") if t_el.name == "meta" else t_el.text
                    title = (title or "").strip()
        except Exception:
            pass
        if not title:
            # Fallback: derive from URL slug
            title = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()

        out.append({
            "id": hashlib.sha1(url.encode()).hexdigest(),
            "title": title,
            "source_url": url,
            "site_name": site_name,
            "summary": "",
            "author": "",
            "published_date": _parse_date(lastmod),
            "_feed": sitemap_url,
        })
        time.sleep(0.2)
    return out


def _fetch_epc_scrape(page_url: str, site_name: str, max_items: int = 20) -> list[dict]:
    """European Policy Centre publishes no RSS. Scrape /publications/ HTML."""
    try:
        r = httpx.get(page_url, headers=HTTP_HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
    except Exception as e:
        print(f"  [skip] {site_name}: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    seen = set()
    out = []
    for a in soup.select("a[href*='/publication/']"):
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https://www.epc.eu" + href
        if href in seen:
            continue
        text = a.get_text(strip=True)
        # Filter labels like 'OP-ED' / 'Read more' / single-word category links
        if not text or len(text) < 20 or text.lower() in ("read more", "publications"):
            continue
        seen.add(href)
        out.append({
            "id": hashlib.sha1(href.encode()).hexdigest(),
            "title": text,
            "source_url": href,
            "site_name": site_name,
            "summary": "",
            "author": "",
            "published_date": "",
            "_feed": page_url,
        })
        if len(out) >= max_items:
            break
    return out


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
