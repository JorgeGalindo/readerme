#!/usr/bin/env python3
"""Papers tab: pull RSS feeds tagged 'papers'. Chronological, grouped by source."""

from datetime import datetime, timezone

from rss import fetch_latest_by_tag
import read_store
import storage

MAX_PER_FEED = 25


def _norm_title(s: str) -> str:
    return (s or "").strip().lower()


def curate_papers() -> dict:
    print("Fetching paper feeds…")
    items = fetch_latest_by_tag("papers", max_per_feed=MAX_PER_FEED)

    # Dedup by source_url and normalized title (NBER programs overlap on the same paper).
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict] = []
    for a in items:
        url = a.get("source_url", "")
        t = _norm_title(a.get("title"))
        if url and url in seen_urls:
            continue
        if t and t in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if t:
            seen_titles.add(t)
        # Map RSS shape -> the simpler shape papers.html consumes.
        out.append({
            "title": a.get("title", ""),
            "url": a.get("source_url", ""),
            "source": a.get("site_name", ""),
            "summary": a.get("summary", ""),
            "author": a.get("author", ""),
            "date": a.get("published_date", ""),
        })

    before = len(out)
    out = read_store.filter_unread(out)
    if len(out) < before:
        print(f"  Filtered {before - len(out)} previously-read items.")

    # Sort each source by date desc; sources rendered in feed-order.
    out.sort(key=lambda x: x.get("date") or "", reverse=True)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "articles": out,
    }
    storage.write_json("papers.json", result)
    print(f"  Total: {len(out)} papers")
    return result


if __name__ == "__main__":
    r = curate_papers()
    for a in r["articles"][:8]:
        print(f"  [{a['source']}] {a['title'][:80]}")
