#!/usr/bin/env python3
"""Thinktanks tab: pull RSS feeds tagged 'thinktank' (grouped by subtag) +
scrape BBVA Research (no RSS available)."""

import json
import pathlib
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from rss import fetch_latest_by_tag

DATA_DIR = pathlib.Path(__file__).parent / "data"
THINKTANKS_FILE = DATA_DIR / "thinktanks.json"

MAX_PER_FEED = 10


def _scrape_bbva_research() -> list[dict]:
    """Scrape BBVA Research Spain publications (no RSS exposed)."""
    import re
    url = "https://www.bbvaresearch.com/geography/espana/"
    try:
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Failed to fetch BBVA Research: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    out = []
    for card in soup.select("article")[:10]:
        link_el = card.find("a", href=True)
        if not link_el:
            continue
        title = card.get_text(strip=True)[:200]
        href = link_el.get("href", "")
        if "|" in title:
            title = title.split("|", 1)[1].strip()
        match = re.search(
            r'\d{1,2}\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{4}',
            title, re.IGNORECASE,
        )
        if match:
            title = title[:match.start()].strip()
        if title and href:
            out.append({
                "title": title,
                "url": href,
                "source": "BBVA Research",
                "summary": "",
                "date": "",
                "subtag": "spain",
            })
    return out


def fetch_thinktanks() -> list[dict]:
    """Fetch latest from all thinktank RSS feeds + scraped sources."""
    items = fetch_latest_by_tag("thinktank", max_per_feed=MAX_PER_FEED)
    print(f"  RSS thinktanks: {len(items)}")

    # Normalize RSS items to the legacy thinktanks shape (url + source + date).
    out = []
    for a in items:
        out.append({
            "title": a.get("title", ""),
            "url": a.get("source_url", ""),
            "source": a.get("site_name", ""),
            "summary": a.get("summary", ""),
            "date": a.get("published_date", ""),
            "subtag": a.get("subtag", ""),
        })

    # BBVA scrape
    print("  Scraping BBVA Research…")
    out.extend(_scrape_bbva_research())

    return out


def curate_thinktanks() -> dict:
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
    for a in result["articles"][:8]:
        print(f"  [{a.get('subtag','?')}/{a['source']}] {a['title'][:60]}")
