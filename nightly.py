#!/usr/bin/env python3
"""Nightly cycle: pull RSS deltas, score Main, refresh España + Thinktanks."""

from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from curator import curate


def run_nightly():
    print(f"\n{'='*50}")
    print(f"readerme nightly — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}\n")

    print("1. Main: scoring new RSS items...")
    result = curate()
    print(f"  Main: {len(result.get('articles', []))} articles in main.json")

    print("\n2. España...")
    from spain import curate_spain
    spain = curate_spain()
    print(f"  España: {len(spain.get('intl', []))} intl + {len(spain.get('spanish', []))} national")

    print("\n3. Thinktanks...")
    from thinktanks import curate_thinktanks
    tt = curate_thinktanks()
    print(f"  Thinktanks: {len(tt.get('articles', []))} publications")


if __name__ == "__main__":
    run_nightly()
