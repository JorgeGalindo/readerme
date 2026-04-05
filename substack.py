"""Fetch and cache all articles from jorgegalindo.substack.com."""

import json
import pathlib
import httpx
from bs4 import BeautifulSoup

DATA_DIR = pathlib.Path(__file__).parent / "data"
CACHE_FILE = DATA_DIR / "substack_articles.json"
SUBSTACK_URL = "https://jorgegalindo.substack.com/api/v1/posts"


def strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


def fetch_all_articles() -> list[dict]:
    """Fetch all articles from the Substack API."""
    articles = []
    offset = 0
    limit = 50

    while True:
        resp = httpx.get(
            SUBSTACK_URL,
            params={"limit": limit, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for post in batch:
            articles.append({
                "title": post.get("title", ""),
                "subtitle": post.get("subtitle", ""),
                "date": post.get("post_date", ""),
                "url": post.get("canonical_url", ""),
                "slug": post.get("slug", ""),
                "wordcount": post.get("wordcount", 0),
                "description": post.get("description", ""),
                "body_text": strip_html(post.get("body_html", "")),
                "cover_image": post.get("cover_image", ""),
                "reaction_count": post.get("reaction_count", 0),
            })
        offset += limit

    return articles


def load_articles(force_refresh: bool = False) -> list[dict]:
    """Load articles from cache or fetch if needed."""
    if CACHE_FILE.exists() and not force_refresh:
        return json.loads(CACHE_FILE.read_text())

    DATA_DIR.mkdir(exist_ok=True)
    articles = fetch_all_articles()
    CACHE_FILE.write_text(json.dumps(articles, ensure_ascii=False, indent=2))
    print(f"Fetched and cached {len(articles)} Substack articles.")
    return articles


if __name__ == "__main__":
    arts = load_articles(force_refresh=True)
    print(f"{len(arts)} articles fetched.")
    for a in arts[:5]:
        print(f"  - {a['title']} ({a['wordcount']} words)")
