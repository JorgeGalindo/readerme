#!/usr/bin/env python3
"""Nightly curation cycle: re-curate and regenerate site."""

from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from curator import curate


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

    print("\n2. Curating España...")
    from spain import curate_spain
    spain = curate_spain()
    print(f"  España: {len(spain.get('intl', []))} intl + {len(spain.get('spanish', []))} national")


if __name__ == "__main__":
    run_nightly()
