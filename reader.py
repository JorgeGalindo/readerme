"""Readwise Reader API: fetch feed, archive articles, save URLs."""

import json
import os
import pathlib
import time
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = pathlib.Path(__file__).parent / "data"
CACHE_FILE = DATA_DIR / "reader_articles.json"
READER_API = "https://readwise.io/api/v3/list/"
READER_SAVE_API = "https://readwise.io/api/v3/save/"
TOKEN = os.getenv("READWISE_TOKEN", "")


def _headers():
    return {"Authorization": f"Token {TOKEN}"}


def _request_with_retry(method, url, **kwargs):
    """Make an HTTP request with retries for flaky connections and rate limits."""
    for attempt in range(5):
        try:
            resp = getattr(httpx, method)(url, timeout=30, **kwargs)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout):
            if attempt == 4:
                raise
            time.sleep(2)


def _parse_doc(doc: dict) -> dict:
    return {
        "id": doc.get("id", ""),
        "title": doc.get("title", ""),
        "author": doc.get("author", ""),
        "source_url": doc.get("source_url", ""),
        "site_name": doc.get("site_name", ""),
        "summary": doc.get("summary", ""),
        "word_count": doc.get("word_count", 0),
        "reading_time": doc.get("reading_time", ""),
        "published_date": doc.get("published_date", ""),
        "category": doc.get("category", ""),
        "location": doc.get("location", ""),
        "image_url": doc.get("image_url", ""),
    }


def fetch_feed(max_items: int = 2000) -> list[dict]:
    """Fetch ALL articles currently in the Reader feed (location=feed)."""
    articles = []

    for category in ("rss", "email"):
        cursor = None
        while len(articles) < max_items:
            params = {
                "location": "feed",
                "category": category,
                "page_size": 100,
            }
            if cursor:
                params["pageCursor"] = cursor

            resp = _request_with_retry("get", READER_API, headers=_headers(), params=params)
            data = resp.json()

            for doc in data.get("results", []):
                articles.append(_parse_doc(doc))

            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            time.sleep(1)  # Avoid rate limiting

    return articles


def fetch_html_content(doc_id: str) -> str:
    """Fetch full HTML content for a specific document."""
    try:
        resp = _request_with_retry("get", READER_API, headers=_headers(),
                                   params={"id": doc_id, "withHtmlContent": 1})
        results = resp.json().get("results", [])
        if results:
            return results[0].get("html_content", "")
    except Exception as e:
        print(f"Failed to fetch content for {doc_id}: {e}")
    return ""


def archive_article(doc_id: str) -> bool:
    """Move an article to archive in Reader."""
    if not TOKEN:
        print(f"Cannot archive {doc_id}: READWISE_TOKEN not set")
        return False
    try:
        resp = httpx.patch(
            f"https://readwise.io/api/v3/update/{doc_id}/",
            headers=_headers(),
            json={"location": "archive"},
            timeout=15,
        )
        if resp.status_code == 404:
            print(f"Archive 404 for {doc_id} — invalid doc ID?")
            return False
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to archive {doc_id}: {e}")
        return False


def mark_as_seen(doc_id: str) -> bool:
    """Mark an article as seen (move out of feed) in Reader."""
    # Reader doesn't have a "seen" state — we archive it
    return archive_article(doc_id)


def save_url(url: str) -> bool:
    """Save a new URL to Reader (goes to archive)."""
    try:
        resp = httpx.post(
            READER_SAVE_API,
            headers=_headers(),
            json={"url": url, "location": "archive"},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to save URL {url}: {e}")
        return False


def load_feed(force_refresh: bool = False) -> list[dict]:
    """Load feed from cache or fetch."""
    if CACHE_FILE.exists() and not force_refresh:
        cache_age = datetime.now().timestamp() - CACHE_FILE.stat().st_mtime
        if cache_age < 7200:
            return json.loads(CACHE_FILE.read_text())

    DATA_DIR.mkdir(exist_ok=True)
    articles = fetch_feed()
    CACHE_FILE.write_text(json.dumps(articles, ensure_ascii=False, indent=2))
    print(f"Fetched {len(articles)} feed articles from Reader.")
    return articles


def fetch_recent(days: int = 2, max_items: int = 300) -> list[dict]:
    """Fetch recent articles from Reader (last N days, feed location)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    articles = []

    for category in ("rss", "email"):
        cursor = None
        while len(articles) < max_items:
            params = {
                "updatedAfter": since,
                "location": "feed",
                "category": category,
                "page_size": 100,
            }
            if cursor:
                params["pageCursor"] = cursor

            resp = _request_with_retry("get", READER_API, headers=_headers(), params=params)
            data = resp.json()

            for doc in data.get("results", []):
                articles.append(_parse_doc(doc))

            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            time.sleep(1)

    return articles


def load_recent(days: int = 2, force_refresh: bool = False) -> list[dict]:
    """Load recent articles from cache or fetch."""
    if CACHE_FILE.exists() and not force_refresh:
        cache_age = datetime.now().timestamp() - CACHE_FILE.stat().st_mtime
        if cache_age < 7200:
            return json.loads(CACHE_FILE.read_text())

    DATA_DIR.mkdir(exist_ok=True)
    articles = fetch_recent(days=days)
    CACHE_FILE.write_text(json.dumps(articles, ensure_ascii=False, indent=2))
    print(f"Fetched {len(articles)} recent Reader articles.")
    return articles


if __name__ == "__main__":
    arts = load_feed(force_refresh=True)
    print(f"{len(arts)} articles in Reader feed.")
    for a in arts[:10]:
        print(f"  - [{a['site_name']}] {a['title']}")
