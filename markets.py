"""Polymarket prediction markets for Main and España, chosen automatically.

Until 2026-11 this file held a hand-picked pool of token ids. Markets resolve
(«Fed baja en junio», «elecciones anticipadas antes del 30 jun») and the page
kept showing them at 0 % with empty charts. Now each night we ask Polymarket's
Gamma API for the most traded open events in a few tags and show those.

Rules, in order:
- an event must be open, end at least a day from now and have traded enough in
  the last 24 h (noise like «gas prices on November 7» falls out by itself);
- events that are one district of a bigger election («Spain General Election:
  Biscay Winner») are skipped, the national market already covers them;
- inside an event, only live markets count: placeholders («Person H»), closed
  or already-expired dates are dropped, and so are outcomes under 1 %;
- each event shows up to three outcomes, most likely first, with 30 days of
  daily prices from the CLOB price history. Date ladders («ceasefire holds
  through…?», «Sánchez out by…?») are cumulative, so they keep calendar order
  and show the three nearest dates.

The CLOB resets connections under parallel load, so histories are fetched one
after another on a single keep-alive client, with retries (~5 s per 25).
"""

from datetime import datetime, timedelta, timezone
import json
import re
import time

import httpx

import storage

MARKETS_FILE_SPAIN = "markets.json"
MARKETS_FILE_MAIN = "markets_main.json"

GAMMA = "https://gamma-api.polymarket.com/events"
CLOB_HISTORY = "https://clob.polymarket.com/prices-history"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Readerme/1.0)"}

# (tag slug on Polymarket, label shown in the card, events to show,
#  min 24h volume in USD, extra title regex to skip or None)
MAIN_SECTIONS = (
    ("geopolitics", "Geopolítica", 2, 20_000, None),
    ("economy", "Economía", 2, 5_000, None),
    # US party primaries two years out crowd out every other election.
    ("world-elections", "Elecciones", 2, 20_000, re.compile(r"\bnominee\b", re.I)),
    ("ai", "IA", 2, 5_000, None),
)
SPAIN_SECTIONS = (
    ("spain", "España", 6, 300, None),
)

MAX_OUTCOMES = 3
MIN_PRICE = 0.01
# «Spain General Election: Biscay Winner», «…: Barcelona 2nd Place»
DISTRICT_RE = re.compile(r":\s.*\b(winner|2nd place|3rd place)\??$", re.I)
NOISE_RE = re.compile(r"#\s*(of\s+)?tweets|up or down|\bprice of\b|\bon (january|february|march|april|may|june|july|"
                      r"august|september|october|november|december) \d{1,2}\b", re.I)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _yes_price(market: dict) -> float | None:
    try:
        prices = market.get("outcomePrices")
        prices = json.loads(prices) if isinstance(prices, str) else prices
        return float(prices[0])
    except (TypeError, ValueError, IndexError):
        return None


def _yes_token(market: dict) -> str | None:
    try:
        tokens = market.get("clobTokenIds")
        tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
        return str(tokens[0])
    except (TypeError, ValueError, IndexError):
        return None


MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")
DATE_LABEL_RE = re.compile(r"^(%s) (\d{1,2})(?:, (\d{4}))?$" % "|".join(MONTHS), re.I)


def _label_date(label: str, fallback: datetime | None) -> datetime | None:
    """«November 30» / «January 31, 2027» → a date; the market's end date
    settles the year when the label omits it."""
    match = DATE_LABEL_RE.match(label.strip())
    if not match:
        return None
    month = MONTHS.index(match.group(1).lower()) + 1
    year = int(match.group(3)) if match.group(3) else (fallback.year if fallback else None)
    if year is None:
        return None
    try:
        return datetime(year, month, int(match.group(2)), tzinfo=timezone.utc)
    except ValueError:
        return None


def live_outcomes(event: dict, now: datetime) -> list[dict]:
    """The event's live markets as outcomes: most likely first, or in calendar
    order when every outcome is a date."""
    outcomes = []
    multi = len(event.get("markets") or []) > 1
    for market in event.get("markets") or []:
        if not market.get("active") or market.get("closed"):
            continue
        if market.get("acceptingOrders") is False:
            continue
        end = _parse_dt(market.get("endDate"))
        # A rung of a date ladder that settles within a day says nothing new.
        if end and end <= now + (timedelta(days=1) if multi else timedelta(0)):
            continue
        price = _yes_price(market)
        token = _yes_token(market)
        if price is None or token is None:
            continue
        if multi and price < MIN_PRICE:
            continue
        change = market.get("oneWeekPriceChange")
        label = (market.get("groupItemTitle") or "").strip() if multi else ""
        outcomes.append({
            "label": label,
            "price": round(price * 100, 1),
            "change_1w": round(float(change) * 100, 1) if isinstance(change, (int, float)) else None,
            "token_id": token,
            "_date": _label_date(label, end) if label else None,
        })
    if multi and outcomes and all(o["_date"] for o in outcomes):
        outcomes.sort(key=lambda o: o["_date"])
    else:
        outcomes.sort(key=lambda o: -o["price"])
    for o in outcomes:
        o.pop("_date")
    return outcomes[:MAX_OUTCOMES]


def pick_events(events: list[dict], *, limit: int, min_volume: float, now: datetime,
                seen: set[str], exclude: re.Pattern | None = None) -> list[dict]:
    """Most traded open events that pass the rules in the module docstring."""
    picked = []
    for event in sorted(events, key=lambda e: -float(e.get("volume24hr") or 0)):
        if len(picked) >= limit:
            break
        event_id = str(event.get("id"))
        title = (event.get("title") or "").strip()
        if event_id in seen or not title:
            continue
        if not event.get("active") or event.get("closed") or event.get("archived"):
            continue
        end = _parse_dt(event.get("endDate"))
        if end is None or end < now + timedelta(days=1):
            continue
        if float(event.get("volume24hr") or 0) < min_volume:
            continue
        if DISTRICT_RE.search(title) or NOISE_RE.search(title):
            continue
        if exclude is not None and exclude.search(title):
            continue
        outcomes = live_outcomes(event, now)
        if not outcomes:
            continue
        seen.add(event_id)
        picked.append({
            "id": event_id,
            "title": title,
            "url": f"https://polymarket.com/event/{event.get('slug')}",
            "end_date": end.date().isoformat(),
            "volume_24h": round(float(event.get("volume24hr") or 0)),
            "outcomes": outcomes,
        })
    return picked


def _fetch_events(client: httpx.Client, tag: str) -> list[dict]:
    resp = client.get(GAMMA, params={
        "tag_slug": tag, "active": "true", "closed": "false",
        "order": "volume24hr", "ascending": "false", "limit": 40,
    })
    resp.raise_for_status()
    return resp.json()


def _fetch_history(client: httpx.Client, token_id: str, attempts: int = 3) -> tuple[list[str], list[float]]:
    """Last 30 days, one point per day."""
    for attempt in range(attempts):
        try:
            resp = client.get(CLOB_HISTORY, params={"market": token_id, "interval": "1m", "fidelity": 1440})
            resp.raise_for_status()
            history = resp.json().get("history", [])
            break
        except (httpx.HTTPError, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(1 + attempt)
    dates, prices = [], []
    for point in history:
        day = datetime.fromtimestamp(point.get("t", 0), tz=timezone.utc).strftime("%Y-%m-%d")
        if dates and dates[-1] == day:
            prices[-1] = round(float(point.get("p", 0)) * 100, 1)
            continue
        dates.append(day)
        prices.append(round(float(point.get("p", 0)) * 100, 1))
    return dates, prices


def build(sections, client: httpx.Client, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    seen: set[str] = set()
    out_sections = []
    for tag, label, limit, min_volume, exclude in sections:
        try:
            events = pick_events(_fetch_events(client, tag), limit=limit, min_volume=min_volume,
                                 now=now, seen=seen, exclude=exclude)
        except httpx.HTTPError as exc:
            print(f"  Polymarket {tag} failed: {exc}")
            continue
        for event in events:
            event["section"] = label
        out_sections.extend(events)

    pending = [o for e in out_sections for o in e["outcomes"]]
    # Resets come in bursts: whatever fails gets a second pass after a pause.
    for pass_no in (1, 2):
        failed = []
        for outcome in pending:
            try:
                outcome["dates"], outcome["prices"] = _fetch_history(client, outcome["token_id"])
            except (httpx.HTTPError, ValueError):
                outcome["dates"], outcome["prices"] = [], []
                failed.append(outcome)
        if not failed or pass_no == 2:
            break
        time.sleep(5)
        pending = failed
    if failed:
        print(f"  {len(failed)} price histories unavailable")
    for outcome in (o for e in out_sections for o in e["outcomes"]):
        outcome.pop("token_id")
    return {"generated_at": now.isoformat(), "events": out_sections}


def _fetch_and_store(name: str, sections, out_file: str) -> dict:
    print(f"Fetching Polymarket events ({name})…")
    with httpx.Client(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        data = build(sections, client)
    for e in data["events"]:
        lead = e["outcomes"][0]
        print(f"  [{e['section']}] {e['title']}: {lead['label'] or 'Sí'} {lead['price']}%")
    if data["events"]:
        storage.write_json(out_file, data)
    else:
        # Keep yesterday's file rather than blanking the section.
        print("  No events found; keeping the previous file.")
    return data


def fetch_markets() -> dict:
    return _fetch_and_store("spain", SPAIN_SECTIONS, MARKETS_FILE_SPAIN)


def fetch_markets_main() -> dict:
    return _fetch_and_store("main", MAIN_SECTIONS, MARKETS_FILE_MAIN)


def load(name: str) -> list[dict]:
    """Events for a template; ignores files written by the old hand-picked pool."""
    data = storage.read_json(name) or {}
    events = data.get("events") if isinstance(data, dict) else None
    return events if isinstance(events, list) else []


if __name__ == "__main__":
    fetch_markets()
    fetch_markets_main()
