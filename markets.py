"""Fetch Polymarket prediction-market history for Spain (España tab) and
Main (global politics) tabs. Each set writes to its own JSON file."""

import json
import pathlib
from datetime import datetime, timezone

import httpx

DATA_DIR = pathlib.Path(__file__).parent / "data"
MARKETS_FILE_SPAIN = DATA_DIR / "markets.json"           # legacy filename
MARKETS_FILE_MAIN = DATA_DIR / "markets_main.json"


SPAIN_MARKETS = {
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

MAIN_MARKETS = {
    "iran_regime": {
        "title": "Caída del régimen iraní antes del 30 jun",
        "token_id": "38397507750621893057346880033441136112987238933685677349709401910643842844855",
        "url": "https://polymarket.com/event/will-the-iranian-regime-fall-by-june-30",
    },
    "russia_ukraine_ceasefire": {
        "title": "Alto el fuego Rusia-Ucrania antes del 30 jun 2026",
        "token_id": "92338023949892178944669766466918011858071833335063600591564160751176113496073",
        "url": "https://polymarket.com/event/russia-x-ukraine-ceasefire-by-june-30-2026",
    },
    "fed_cut_25_jun": {
        "title": "Fed baja 25 bps en junio 2026",
        "token_id": "65193234666628291664907888364936366210889305490897648116746073820519263548476",
        "url": "https://polymarket.com/event/will-the-fed-decrease-interest-rates-by-25-bps-after-the-june-2026-meeting",
    },
    "china_taiwan_2026": {
        "title": "Invasión china de Taiwán antes de fin de 2026",
        "token_id": "94559586571241563470235664821564670251180951772614764383113614156422396181162",
        "url": "https://polymarket.com/event/will-china-invade-taiwan-before-2027",
    },
}


def _fetch_one(token_id: str) -> tuple[list[str], list[float], float]:
    """Return (dates, prices, current) for one Polymarket token."""
    resp = httpx.get(
        "https://clob.polymarket.com/prices-history",
        params={"market": token_id, "interval": "all", "fidelity": 360},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    history = data.get("history", [])
    dates: list[str] = []
    prices: list[float] = []
    for point in history:
        ts = point.get("t", 0)
        price = float(point.get("p", 0))
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        dates.append(dt.strftime("%Y-%m-%d"))
        prices.append(round(price * 100, 1))
    current = prices[-1] if prices else 0
    return dates, prices, current


def _fetch_set(name: str, markets: dict, out_file: pathlib.Path) -> dict:
    print(f"Fetching Polymarket data ({name})…")
    out: dict = {}
    for key, market in markets.items():
        try:
            dates, prices, current = _fetch_one(market["token_id"])
            out[key] = {
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
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def fetch_markets() -> dict:
    return _fetch_set("spain", SPAIN_MARKETS, MARKETS_FILE_SPAIN)


def fetch_markets_main() -> dict:
    return _fetch_set("main", MAIN_MARKETS, MARKETS_FILE_MAIN)


if __name__ == "__main__":
    fetch_markets()
    fetch_markets_main()
