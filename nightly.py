#!/usr/bin/env python3
"""Nightly curation cycle: process feedback, re-curate, regenerate site."""

import json
import pathlib
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from reader import archive_article, save_url
from curator import curate

DATA_DIR = pathlib.Path(__file__).parent / "data"
FEEDBACK_FILE = DATA_DIR / "feedback.json"
FEEDBACK_PROCESSED_FILE = DATA_DIR / "feedback_processed.json"


def process_pending_feedback():
    """Process Sí/No feedback that hasn't been synced to Reader yet."""
    if not FEEDBACK_FILE.exists():
        print("No feedback to process.")
        return

    feedback = json.loads(FEEDBACK_FILE.read_text())

    # Load already processed IDs
    processed = set()
    if FEEDBACK_PROCESSED_FILE.exists():
        processed = set(json.loads(FEEDBACK_PROCESSED_FILE.read_text()))

    new_processed = []
    for i, entry in enumerate(feedback):
        key = f"{entry.get('date', '')}_{entry.get('title', '')}"
        if key in processed:
            continue

        doc_id = entry.get("id", "")
        source_url = entry.get("source_url", "")
        section = entry.get("section", "")
        liked = entry.get("liked", True)

        synced = False
        if section == "feeds" and doc_id:
            # Both Sí and No → archive (removes from feed)
            synced = archive_article(doc_id)
            action = "archived" if liked else "marked seen"
        elif liked and section in ("bubble", "abundance") and source_url:
            # Sí on web article → save to Reader
            synced = save_url(source_url)
            action = "saved to Reader"
        else:
            synced = True  # Nothing to sync
            action = "skipped"

        if synced:
            new_processed.append(key)
            print(f"  [{action}] {entry.get('title', '?')[:60]}")

    # Update processed list
    all_processed = list(processed) + new_processed
    FEEDBACK_PROCESSED_FILE.write_text(json.dumps(all_processed))
    print(f"Processed {len(new_processed)} feedback entries.")


def run_nightly():
    """Full nightly cycle."""
    print(f"\n{'='*50}")
    print(f"readerme nightly — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}\n")

    print("1. Processing pending feedback...")
    process_pending_feedback()

    print("\n2. Curating fresh feed (Mundo)...")
    result = curate()

    n_articles = len(result.get("articles", []))
    n_thinktank = len(result.get("thinktank", []))
    n_abundance = len(result.get("abundance", []))
    total = result.get("article_count_total", 0)

    print(f"  Mundo: {n_thinktank} thinktank + {n_abundance} abundance + {n_articles} feeds (from {total} in Reader)")

    print("\n3. Curating España...")
    from spain import curate_spain
    spain = curate_spain()
    print(f"  España: {len(spain.get('intl', []))} intl + {len(spain.get('spanish', []))} national")


if __name__ == "__main__":
    run_nightly()
