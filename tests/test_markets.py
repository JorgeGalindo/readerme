import json
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import httpx

import markets

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def iso(delta_days: float) -> str:
    return (NOW + timedelta(days=delta_days)).isoformat().replace("+00:00", "Z")


def market(label="", price=0.5, *, active=True, closed=False, ends=30, token="t", change=0.02):
    return {
        "groupItemTitle": label, "outcomePrices": json.dumps([str(price), str(1 - price)]),
        "clobTokenIds": json.dumps([token, token + "-no"]), "active": active, "closed": closed,
        "acceptingOrders": active, "endDate": iso(ends), "oneWeekPriceChange": change,
    }


def event(title, *mkts, eid=None, volume=50_000, ends=30, slug="slug", **extra):
    return {"id": eid or title, "title": title, "slug": slug, "active": True, "closed": False,
            "archived": False, "endDate": iso(ends), "volume24hr": volume,
            "markets": list(mkts), **extra}


def pick(events, **kw):
    kw.setdefault("limit", 10)
    kw.setdefault("min_volume", 1_000)
    return markets.pick_events(events, now=NOW, seen=kw.pop("seen", set()), **kw)


class PickEventsTests(unittest.TestCase):
    def test_most_traded_first_and_limit(self):
        events = [event("B", market(), volume=2_000), event("A", market(), volume=9_000),
                  event("C", market(), volume=5_000)]
        self.assertEqual([e["title"] for e in pick(events, limit=2)], ["A", "C"])

    def test_resolved_expiring_thin_and_noise_events_are_skipped(self):
        events = [
            event("Closed", market(), closed=True),
            event("Ends tonight", market(), ends=0.5),
            event("Already ended", market(), ends=-9),
            event("Thin", market(), volume=10),
            event("Spain General Election: Biscay Winner", market("PNV"), market("EH Bildu")),
            event("Elon Musk # tweets November 5 - November 7, 2026?", market()),
            event("Gas prices on November 30?", market()),
            event("Keep me", market()),
        ]
        self.assertEqual([e["title"] for e in pick(events)], ["Keep me"])

    def test_section_specific_exclusion(self):
        exclude = markets.MAIN_SECTIONS[2][4]
        events = [event("Republican Presidential Nominee 2028", market("Vance"), market("Rubio")),
                  event("Next French Presidential Election", market("Le Pen"), market("Lisnard"))]
        self.assertEqual([e["title"] for e in pick(events, exclude=exclude)],
                         ["Next French Presidential Election"])

    def test_an_event_already_shown_in_another_section_is_not_repeated(self):
        seen = set()
        first = pick([event("Fed Decision in December?", market(), eid="1")], seen=seen)
        second = pick([event("Fed Decision in December?", market(), eid="1")], seen=seen)
        self.assertEqual((len(first), len(second)), (1, 0))

    def test_event_without_live_markets_is_dropped(self):
        events = [event("Only placeholders", market("Person H", active=False), market("Person I", active=False))]
        self.assertEqual(pick(events), [])


class OutcomeTests(unittest.TestCase):
    def outcomes(self, *mkts):
        return markets.live_outcomes(event("E", *mkts), NOW)

    def test_multi_outcome_events_show_three_most_likely_without_dead_or_tiny_ones(self):
        rows = self.outcomes(market("Feijóo", 0.875), market("Sánchez", 0.112), market("Abascal", 0.011),
                             market("Nobody", 0.004), market("Person H", 0.5, active=False),
                             market("Closed", 0.6, closed=True), market("Díaz", 0.02))
        self.assertEqual([(r["label"], r["price"]) for r in rows],
                         [("Feijóo", 87.5), ("Sánchez", 11.2), ("Díaz", 2.0)])
        self.assertEqual(rows[0]["change_1w"], 2.0)

    def test_binary_market_has_no_label_and_keeps_low_prices(self):
        rows = markets.live_outcomes(event("Will China invade Taiwan?", market(price=0.004)), NOW)
        self.assertEqual([(r["label"], r["price"]) for r in rows], [("", 0.4)])

    def test_date_ladders_keep_calendar_order_and_drop_rungs_settling_today(self):
        rows = self.outcomes(market("January 31, 2027", 0.835, ends=85),
                             market("November 7", 0.97, ends=0.5),
                             market("December 31, 2026", 0.145, ends=54),
                             market("January 15, 2027", 0.515, ends=69),
                             market("March 31", 0.9, ends=144))
        self.assertEqual([r["label"] for r in rows],
                         ["December 31, 2026", "January 15, 2027", "January 31, 2027"])

    def test_missing_weekly_change_is_none(self):
        rows = self.outcomes(market("A", 0.6, change=None), market("B", 0.3))
        self.assertIsNone(rows[0]["change_1w"])


class BuildTests(unittest.TestCase):
    def test_history_is_daily_and_failures_leave_empty_series(self):
        day = int(NOW.timestamp())
        calls = {"history": 0}

        def respond(request):
            if request.url.host == "gamma-api.polymarket.com":
                tag = request.url.params["tag_slug"]
                return httpx.Response(200, json=[event(f"Event {tag}", market("A", 0.7, token="ok"),
                                                       market("B", 0.2, token="bad"), eid=tag)])
            calls["history"] += 1
            if request.url.params["market"] == "bad":
                return httpx.Response(500)
            return httpx.Response(200, json={"history": [
                {"t": day - 86400, "p": 0.6}, {"t": day - 60, "p": 0.65}, {"t": day, "p": 0.7}]})

        with patch.object(markets.time, "sleep"), \
             httpx.Client(transport=httpx.MockTransport(respond)) as client:
            data = markets.build((("spain", "España", 3, 0, None),), client, now=NOW)
        [ev] = data["events"]
        self.assertEqual(ev["section"], "España")
        self.assertEqual(ev["url"], "https://polymarket.com/event/slug")
        good, bad = ev["outcomes"]
        self.assertEqual(good["dates"], ["2026-11-06", "2026-11-07"])
        self.assertEqual(good["prices"], [60.0, 70.0])
        self.assertEqual((bad["dates"], bad["prices"]), ([], []))
        self.assertNotIn("token_id", good)
        # one ok; the failing one gets three attempts, a pause, and three more
        self.assertEqual(calls["history"], 1 + 3 + 3)

    def test_load_ignores_the_old_hand_picked_format(self):
        old = {"starmer_dec": {"title": "Starmer", "current": 0, "dates": [], "prices": []}}
        with patch.object(markets.storage, "read_json", return_value=old):
            self.assertEqual(markets.load("markets.json"), [])
        with patch.object(markets.storage, "read_json", return_value={"events": [{"title": "x"}]}):
            self.assertEqual(markets.load("markets.json"), [{"title": "x"}])


if __name__ == "__main__":
    unittest.main()
