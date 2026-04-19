#!/usr/bin/env python3
"""Fetch latest publications from Spanish thinktanks."""

import json
import pathlib
import time

import httpx
from bs4 import BeautifulSoup

DATA_DIR = pathlib.Path(__file__).parent / "data"
THINKTANKS_FILE = DATA_DIR / "thinktanks.json"

# RSS feeds
FEEDS = {
    "Real Instituto Elcano": "https://www.realinstitutoelcano.org/feed/",
    "Fedea": "https://fedea.net/feed/",
}

# Scraped sources (no RSS)
SCRAPE_SOURCES = {
    "BBVA Research": "https://www.bbvaresearch.com/geography/espana/",
}


def _fetch_rss(source: str, url: str, max_items: int = 10) -> list[dict]:
    """Fetch articles from an RSS feed."""
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Failed to fetch {source}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "xml")
    items = soup.find_all("item")
    articles = []

    for item in items[:max_items]:
        title = item.find("title")
        link = item.find("link")
        desc = item.find("description")
        pub_date = item.find("pubDate")

        if not title or not link:
            continue

        articles.append({
            "title": title.text.strip(),
            "url": link.text.strip(),
            "source": source,
            "summary": (desc.text.strip()[:300] if desc else ""),
            "date": (pub_date.text.strip() if pub_date else ""),
        })

    return articles


def _scrape_bbva_research() -> list[dict]:
    """Scrape BBVA Research Spain publications."""
    url = "https://www.bbvaresearch.com/geography/espana/"
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Failed to fetch BBVA Research: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    for card in soup.select("article")[:10]:
        link_el = card.find("a", href=True)
        if not link_el:
            continue
        title = card.get_text(strip=True)[:200]
        href = link_el.get("href", "")

        # Clean up title: remove date suffix and "España |" prefix
        # Titles come as "España | Title16 abril 2026Description..."
        clean_title = title
        if "|" in clean_title:
            clean_title = clean_title.split("|", 1)[1].strip()
        # Truncate at first digit sequence that looks like a date
        import re
        match = re.search(r'\d{1,2}\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{4}', clean_title, re.IGNORECASE)
        if match:
            clean_title = clean_title[:match.start()].strip()

        if clean_title and href:
            articles.append({
                "title": clean_title,
                "url": href,
                "source": "BBVA Research",
                "summary": "",
                "date": "",
            })

    return articles


def fetch_thinktanks() -> list[dict]:
    """Fetch latest publications from all thinktank sources."""
    all_articles = []

    # RSS feeds
    for source, url in FEEDS.items():
        print(f"  Fetching {source}...")
        articles = _fetch_rss(source, url)
        all_articles.extend(articles)
        time.sleep(0.5)

    # Scraped sources
    print(f"  Fetching BBVA Research...")
    all_articles.extend(_scrape_bbva_research())

    # Strip HTML from summaries
    for a in all_articles:
        if a["summary"] and "<" in a["summary"]:
            a["summary"] = BeautifulSoup(a["summary"], "html.parser").get_text(strip=True)[:300]

    return all_articles


def curate_thinktanks() -> dict:
    """Fetch and save thinktank publications."""
    from datetime import datetime, timezone

    print("Fetching thinktank publications...")
    articles = fetch_thinktanks()
    print(f"  Total: {len(articles)} publications")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
    }

    DATA_DIR.mkdir(exist_ok=True)
    THINKTANKS_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    result = curate_thinktanks()
    for a in result["articles"][:5]:
        print(f"  [{a['source']}] {a['title'][:60]}")
        print(f"    {a['url']}")
