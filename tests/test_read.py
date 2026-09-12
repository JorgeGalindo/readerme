import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import read_store
import server


class ReadStoreTests(unittest.TestCase):
    def test_url_keys_match_browser_fixtures(self):
        cases = json.loads(Path(__file__).with_name("read-url-cases.json").read_text())
        for case in cases:
            with self.subTest(raw=case["raw"]):
                self.assertEqual(read_store.norm_url(case["raw"]), case["normalized"])

    def test_existing_ledger_keys_are_normalized_when_loaded(self):
        with patch.object(read_store, "_kv_enabled", return_value=False), \
             patch.object(read_store, "_local_load", return_value={"https://ejemplo.es/café/": "date"}):
            self.assertTrue(read_store.is_read("https://ejemplo.es/caf%C3%A9?utm_source=x"))

    def test_remote_mark_failure_does_not_fall_back_to_ephemeral_local_storage(self):
        with patch.object(read_store, "_kv_enabled", return_value=True), \
             patch.object(read_store, "_kv_mark", side_effect=OSError("offline")), \
             patch.object(read_store, "_local_save") as local:
            with self.assertRaises(OSError):
                read_store.mark("https://example.com/a")
            local.assert_not_called()

    def test_remote_clear_failure_preserves_local_storage(self):
        with patch.object(read_store, "_kv_enabled", return_value=True), \
             patch.object(read_store, "_kv_clear", side_effect=OSError("offline")), \
             patch.object(read_store, "_local_save") as local:
            with self.assertRaises(OSError):
                read_store.clear()
            local.assert_not_called()

    def test_remote_mutations_require_a_valid_acknowledgement(self):
        for invalid in [None, -1, 2, "1", True, {}]:
            with self.subTest(result=invalid), patch.object(read_store, "_kv_call", return_value=invalid):
                with self.assertRaises(RuntimeError):
                    read_store._kv_mark("https://example.com/a", "date")
                with self.assertRaises(RuntimeError):
                    read_store._kv_clear()
        for valid in (0, 1):
            with patch.object(read_store, "_kv_call", return_value=valid):
                read_store._kv_mark("https://example.com/a", "date")
                read_store._kv_clear()

    def test_invalid_rest_responses_are_not_successful_writes(self):
        for body in [{}, {"error": "unavailable"}, [], None]:
            response = Mock()
            response.json.return_value = body
            with self.subTest(body=body), \
                 patch.object(read_store, "_kv_url", return_value="https://example.invalid"), \
                 patch.object(read_store, "_kv_token", return_value="test-token"), \
                 patch.object(read_store.httpx, "post", return_value=response):
                with self.assertRaises(RuntimeError):
                    read_store._kv_call(["DEL", "test-ledger"])


class ReadApiTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_invalid_mark_payloads_return_400_without_writing(self):
        with patch.object(read_store, "mark") as mark:
            for value in [None, [], "text", {}, {"url": 42}, {"url": " "}, {"url": None}]:
                with self.subTest(payload=value):
                    response = self.client.post("/api/read", json=value)
                    self.assertEqual(response.status_code, 400)
            mark.assert_not_called()

    def test_mark_failure_is_retryable_and_success_requires_a_write(self):
        with patch.object(read_store, "mark", side_effect=OSError("offline")):
            response = self.client.post("/api/read", json={"url": "https://example.com/a"})
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json["ok"])
        with patch.object(read_store, "mark") as mark:
            response = self.client.post("/api/read", json={"url": " https://example.com/a "})
            self.assertEqual(response.status_code, 200)
            mark.assert_called_once_with("https://example.com/a")

    def test_clear_failure_is_not_reported_as_success(self):
        with patch.object(read_store, "clear", side_effect=OSError("offline")):
            response = self.client.post("/api/read/clear")
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json["ok"])
        with patch.object(read_store, "clear") as clear:
            response = self.client.post("/api/read/clear")
            self.assertTrue(response.json["ok"])
            clear.assert_called_once()

    def test_all_read_is_distinguished_from_an_empty_feed_on_all_article_pages(self):
        url = "https://example.com/a"
        documents = {
            "main.json": {"articles": [{"source_url": url, "title": "Prueba", "site_name": "Source"}]},
            "papers.json": {"articles": [{"url": url, "title": "Prueba", "source": "Source"}]},
            "thinktanks.json": {"articles": [{"url": url, "title": "Prueba", "source": "Source", "subtag": "classic"}]},
        }
        with patch.object(server.storage, "read_json", side_effect=lambda name: documents.get(name, {})), \
             patch.object(read_store, "load", return_value={url: "date"}):
            for route in ("/main", "/papers", "/thinktanks"):
                with self.subTest(route=route):
                    response = self.client.get(route)
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertIn("Todo leído por ahora.", html)
                    self.assertNotIn('data-url="' + url + '"', html)
                    self.assertNotIn("python run.py", html)

    def test_all_pages_and_the_shared_script_are_served(self):
        with patch.object(server.storage, "read_json", return_value={}), \
             patch.object(server.storage, "exists", return_value=False), \
             patch.object(read_store, "load", return_value={}):
            for route in ("/main", "/espana", "/papers", "/thinktanks"):
                with self.subTest(route=route):
                    response = self.client.get(route)
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertEqual(html.count('src="/static/read.js"'), 1)
                    self.assertIn('id="readStatus"', html)
            response = self.client.get("/static/read.js")
            try:
                self.assertEqual(response.status_code, 200)
            finally:
                response.close()


if __name__ == "__main__":
    unittest.main()
