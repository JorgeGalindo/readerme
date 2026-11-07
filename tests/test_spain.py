import json
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

import server
import spain
import spain_ai


def article(i, source):
    return {"title": f"Titular {i}", "link": f"https://example.com/{i}", "author": "",
            "summary": f"Resumen {i}", "date": "", "source": source}


CANDIDATES = [article(i, "El País") for i in range(3)] + [article(i, "El Mundo") for i in range(3, 5)]


class RssRadarTests(unittest.TestCase):
    def test_takes_the_newest_item_from_each_paper_in_turn(self):
        radar = spain.rss_radar(CANDIDATES, size=4)
        self.assertEqual([a["title"] for a in radar], ["Titular 0", "Titular 3", "Titular 1", "Titular 4"])
        self.assertEqual(radar[0]["risk_summary"], "Resumen 0")

    def test_repeated_titles_are_shown_once(self):
        dup = [article(1, "El País"), {**article(1, "El Mundo")}]
        self.assertEqual(len(spain.rss_radar(dup)), 1)

    def test_curate_spain_stores_candidates_without_calling_a_model(self):
        written = {}
        with patch.object(spain, "fetch_intl_spain", return_value=[]), \
             patch.object(spain, "fetch_spanish_media", return_value=CANDIDATES), \
             patch.object(spain.storage, "write_json", side_effect=lambda n, o: written.update({n: o})):
            spain.curate_spain()
        data = written["spain.json"]
        self.assertEqual(data["candidates"], CANDIDATES)
        self.assertEqual(data["radar_source"], "rss")
        self.assertEqual(len(data["spanish"]), 5)


class SpainAiTests(unittest.TestCase):
    spain_data = {"generated_at": "2026-11-07T02:01:00+00:00", "candidates": CANDIDATES, "intl": []}

    def test_prompt_lists_numbered_candidates_polls_and_markets(self):
        prompt = spain_ai.build_prompt(
            self.spain_data,
            {"averages": {"PP": [33.0, 33.4], "PSOE": [27.1]}, "bloc": {"right_bloc": 47}},
            {"events": [{"title": "Next Prime Minister of Spain?",
                         "outcomes": [{"label": "Feijóo", "price": 87.5}]}]})
        self.assertIn('[4] "Titular 4" — El Mundo', prompt)
        self.assertIn("- PP: 33.4%", prompt)
        self.assertIn("Next Prime Minister of Spain?: Feijóo 87.5%", prompt)

    def test_apply_keeps_valid_unique_picks_and_marks_the_day(self):
        answer = {"radar": [{"index": 4, "summary_es": " Riesgo A "}, {"index": 4, "summary_es": "dup"},
                            {"index": 99, "summary_es": "fuera"}, {"index": 0, "summary_es": "Riesgo B"}],
                  "briefing": "Párrafo uno.\n\nPárrafo dos."}
        out = spain_ai.apply(self.spain_data, answer)
        self.assertEqual([a["title"] for a in out["spanish"]], ["Titular 4", "Titular 0"])
        self.assertEqual(out["spanish"][0]["risk_summary"], "Riesgo A")
        self.assertEqual(out["radar_source"], "claude")
        self.assertEqual(out["ai_for"], self.spain_data["generated_at"])
        self.assertEqual(out["candidates"], CANDIDATES)

    def test_apply_refuses_an_answer_with_no_usable_pick(self):
        with self.assertRaises(RuntimeError):
            spain_ai.apply(self.spain_data, {"radar": [{"index": 50, "summary_es": "x"}], "briefing": ""})

    def test_claude_runs_without_tools_and_returns_the_structured_output(self):
        class Done:
            returncode = 0
            stderr = ""
            stdout = json.dumps({"is_error": False, "structured_output": {"radar": [], "briefing": "x"}})
        with patch.object(spain_ai.subprocess, "run", return_value=Done()) as run:
            self.assertEqual(spain_ai.ask_claude("hola")["briefing"], "x")
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[1], "-p")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--json-schema", cmd)
        self.assertEqual(run.call_args.kwargs["input"], "hola")


class SpainPageTests(unittest.TestCase):
    def render(self, spain_data):
        files = {"spain.json": spain_data, "polls.json": {}, "markets.json": {"events": [{
            "id": "1", "title": "Next Prime Minister of Spain?", "url": "https://polymarket.com/event/x",
            "section": "España", "end_date": "2026-11-30", "volume_24h": 1,
            "outcomes": [{"label": "Feijóo", "price": 87.5, "change_1w": 3.5, "dates": [], "prices": []},
                         {"label": "Abascal", "price": 0.4, "change_1w": -0.2, "dates": [], "prices": []}]}]}}
        with patch.object(server.storage, "read_json", side_effect=lambda n: files.get(n)), \
             patch.object(server.read_store, "load", return_value={}):
            response = server.app.test_client().get("/espana")
        self.assertEqual(response.status_code, 200)
        return BeautifulSoup(response.data, "html.parser")

    def test_todays_claude_briefing_is_shown_as_paragraphs(self):
        page = self.render({"generated_at": "2026-11-07T02:01:00+00:00", "ai_for": "2026-11-07T02:01:00+00:00",
                            "ai_at": "2026-11-07T06:30:00+00:00", "radar_source": "claude",
                            "briefing": "Uno.\n\nDos.", "spanish": [article(1, "El País")], "intl": []})
        self.assertEqual([p.get_text() for p in page.select(".briefing-text p")], ["Uno.", "Dos."])
        self.assertIsNone(page.select_one(".radar-note"))
        self.assertIsNone(page.select_one("audio"))

    def test_a_briefing_from_an_older_nightly_is_hidden_and_the_radar_says_so(self):
        page = self.render({"generated_at": "2026-11-08T02:01:00+00:00", "ai_for": "2026-11-07T02:01:00+00:00",
                            "radar_source": "claude", "briefing": "Viejo.",
                            "spanish": [article(1, "El País")], "intl": []})
        self.assertIsNone(page.select_one(".briefing"))
        self.assertIn("sin selección de Claude", page.select_one(".radar-note").get_text())

    def test_market_cards_use_spanish_number_format(self):
        page = self.render({"generated_at": "", "spanish": [], "intl": []})
        rows = [[s.get_text() for s in li.select("span")] for li in page.select(".market-outcome")]
        self.assertEqual(rows, [["Feijóo", "87,5%", "+3,5"], ["Abascal", "<1%", "="]])
        self.assertEqual(page.select_one(".market-title")["href"], "https://polymarket.com/event/x")
        self.assertIsNotNone(page.select_one("#marketsData"))


class ApiFreeServerTests(unittest.TestCase):
    def test_removed_model_and_audio_routes(self):
        client = server.app.test_client()
        self.assertEqual(client.post("/api/share-text", json={}).status_code, 404)
        self.assertEqual(client.get("/api/briefing.mp3").status_code, 404)


if __name__ == "__main__":
    unittest.main()
