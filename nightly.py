#!/usr/bin/env python3
"""Nightly curation cycle: fetch from Reader, curate, archive."""

from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from curator import curate
from reader import archive_all


def run_nightly():
    """Full nightly cycle."""
    print(f"\n{'='*50}")
    print(f"readerme nightly — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}\n")

    print("1. Curating fresh feed (Mundo)...")
    result = curate()

    n_articles = len(result.get("articles", []))
    n_thinktank = len(result.get("thinktank", []))
    n_abundance = len(result.get("abundance", []))
    total = result.get("article_count_total", 0)

    print(f"  Mundo: {n_thinktank} thinktank + {n_abundance} abundance + {n_articles} feeds (from {total} in Reader)")

    # Archive all fetched articles in Reader (clean the inbox)
    fetched_ids = result.get("_fetched_ids", [])
    if fetched_ids:
        print(f"\n2. Archiving {len(fetched_ids)} articles in Reader...")
        archived = archive_all(fetched_ids)
        print(f"  Archived {archived}/{len(fetched_ids)}")

    print(f"\n3. Curating España...")
    from spain import curate_spain
    spain = curate_spain()
    print(f"  España: {len(spain.get('intl', []))} intl + {len(spain.get('spanish', []))} national")


if __name__ == "__main__":
    run_nightly()
