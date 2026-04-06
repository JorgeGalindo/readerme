"""Fetch Polymarket prediction market data for Spain."""

import json
import pathlib
from datetime import datetime, timezone

import httpx

DATA_DIR = pathlib.Path(__file__).parent / "data"
MARKETS_FILE = DATA_DIR / "markets.json"

MARKETS = {
    "snap_june": {
        "title": "Elecciones anticipadas antes del 30 jun 2026",
        "token_id": "22727676348515372003751667928661129938953357934816532759741382381194930135311",
        "url": "https://polymarket.com/event/spain-snap-election-called-by/spain-snap-election-called-by-june-30-2026",
    },
    "snap_2026": {
        "title": "Elecciones anticipadas en 2026",
        "token_id": "59503554798824057287666406378885313688964980592517621433937122029072326338100",
        "url": "https://polymarket.com/event/spain-snap-election-called-in-2026",
    },
}


def fetch_markets() -> dict:
    """Fetch price history for Spain prediction markets."""
    print("Fetching Polymarket data...")
    result = {}

    for key, market in MARKETS.items():
        try:
            resp = httpx.get(
                "https://clob.polymarket.com/prices-history",
                params={"market": market["token_id"], "interval": "all", "fidelity": 360},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            history = data.get("history", [])
            dates = []
            prices = []
            for point in history:
                ts = point.get("t", 0)
                price = float(point.get("p", 0))
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                dates.append(dt.strftime("%Y-%m-%d"))
                prices.append(round(price * 100, 1))

            current = prices[-1] if prices else 0

            result[key] = {
                "title": market["title"],
                "url": market["url"],
                "dates": dates,
                "prices": prices,
                "current": current,
            }
            print(f"  {market['title']}: {current}% ({len(dates)} points)")

        except Exception as e:
            print(f"  Failed {key}: {e}")

    DATA_DIR.mkdir(exist_ok=True)
    MARKETS_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    fetch_markets()
