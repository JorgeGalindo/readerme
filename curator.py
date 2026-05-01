"""Main tab curator: fetch RSS deltas, dedup, carry-over, save main.json.

No Claude scoring/tagging — items are shown chronologically from their feeds.
"""

import json
import pathlib
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from rss import fetch_by_tag
import read_store

load_dotenv()

DATA_DIR = pathlib.Path(__file__).parent / "data"
MAIN_FILE = DATA_DIR / "main.json"

CARRY_OVER_DAYS = 14


def _norm_title(s: str) -> str:
    return (s or "").strip().lower()


def curate() -> dict:
    """Fetch new RSS items (tag=main), dedup, carry over recent unread, save."""
    new_items = fetch_by_tag("main")
    print(f"Fetched {len(new_items)} new RSS items (main).")

    now_iso = datetime.now(timezone.utc).isoformat()
    for a in new_items:
        a.setdefault("_added_at", now_iso)

    # Carry over previously-curated items still inside the carry-over window.
    carried = []
    if MAIN_FILE.exists():
        try:
            prev = json.loads(MAIN_FILE.read_text())
            cutoff = (datetime.now(timezone.utc) - timedelta(days=CARRY_OVER_DAYS)).isoformat()
            for old in prev.get("articles", []):
                added = old.get("_added_at") or old.get("published_date") or ""
                if added and added < cutoff:
                    continue
                carried.append(old)
        except Exception as e:
            print(f"  Carry-over skipped: {e}")
    print(f"  Carrying over {len(carried)} previously-curated items.")

    # Dedup by source_url and normalized title — new items take precedence.
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict] = []
    for a in new_items + carried:
        url = a.get("source_url", "")
        title = _norm_title(a.get("title"))
        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        out.append(a)

    # Drop anything the user has already marked as read (server-side ledger).
    before = len(out)
    out = read_store.filter_unread(out)
    if len(out) < before:
        print(f"  Filtered {before - len(out)} previously-read items.")

    # Sort newest first by published_date (fallback to _added_at).
    out.sort(key=lambda a: a.get("published_date") or a.get("_added_at") or "", reverse=True)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "article_count_total": len(out),
        "articles": out,
    }

    DATA_DIR.mkdir(exist_ok=True)
    MAIN_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Wrote {len(out)} articles to main.json.")
    return result


if __name__ == "__main__":
    curate()
