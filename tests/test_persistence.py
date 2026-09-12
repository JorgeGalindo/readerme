import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import dotenv
with patch.object(dotenv, "load_dotenv"):
    import curator
import local_files
import read_store
import rss
import storage


class RSSPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.feed = "https://example.com/feed"
        self.article = {"id": "new", "title": "Nueva noticia", "source_url": "https://example.com/new"}
        self.saved = {
            "feeds.json": [{"rss_url": self.feed, "site_name": "Example", "tag": "main"}],
            "rss_state.json": {self.feed: "old"},
        }
        self.writes = []
        self.fail_file = None
        self.start_patch(patch.object(storage, "read_json", side_effect=lambda name: copy.deepcopy(self.saved.get(name))))
        self.start_patch(patch.object(storage, "write_json", side_effect=self.write))
        self.start_patch(patch.object(read_store, "filter_unread", side_effect=lambda items: items))
        self.start_patch(patch.object(rss, "_fetch_one", side_effect=self.fetch))
        self.start_patch(patch.object(rss.time, "sleep"))
        self.start_patch(patch.object(rss.httpx, "get", side_effect=AssertionError("Tests must not access the network")))
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def start_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self, url, site, last):
        return ([] if last == "new" else [copy.deepcopy(self.article)], "new")

    def write(self, name, value):
        self.writes.append(name)
        if name == self.fail_file:
            raise OSError("simulated write failure")
        self.saved[name] = copy.deepcopy(value)

    def test_failed_article_save_keeps_previous_feed_position_and_retries(self):
        self.fail_file = "main.json"
        with self.assertRaises(OSError):
            curator.curate()
        self.assertEqual(self.saved["rss_state.json"][self.feed], "old")
        self.assertNotIn("main.json", self.saved)
        self.fail_file = None
        result = curator.curate()
        self.assertEqual([a["id"] for a in result["articles"]], ["new"])
        self.assertEqual(self.saved["rss_state.json"][self.feed], "new")
        self.assertEqual(self.writes[-2:], ["main.json", "rss_state.json"])

    def test_failed_feed_checkpoint_retries_without_duplicate_articles(self):
        self.fail_file = "rss_state.json"
        with self.assertRaises(OSError):
            curator.curate()
        self.assertIn("main.json", self.saved)
        self.assertEqual(len(self.saved["main.json"]["articles"]), 1)
        self.assertEqual(self.saved["rss_state.json"][self.feed], "old")
        self.fail_file = None
        result = curator.curate()
        self.assertEqual(len(result["articles"]), 1)
        self.assertEqual(self.saved["rss_state.json"][self.feed], "new")

    def test_fetch_batch_does_not_acknowledge_until_requested(self):
        batch = rss.fetch_batch_by_tag("main", sleep_between=0)
        self.assertEqual(len(batch.articles), 1)
        self.assertEqual(self.writes, [])
        batch.commit()
        self.assertEqual(self.saved["rss_state.json"][self.feed], "new")

    def test_next_successful_run_carries_over_article_without_fetching_it_again(self):
        curator.curate()
        result = curator.curate()
        self.assertEqual([a["id"] for a in result["articles"]], ["new"])


class AtomicFileTests(unittest.TestCase):
    def setUp(self):
        # All fixtures stay inside this repository, including temporary files.
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.path.write_bytes(b'{"previous": true}')

    def test_success_replaces_the_file_and_leaves_no_temporary_files(self):
        local_files.atomic_write(self.path, b'{"new": true}')
        self.assertEqual(self.path.read_bytes(), b'{"new": true}')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_replace_preserves_previous_content_and_cleans_temporary(self):
        with patch.object(local_files.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                local_files.atomic_write(self.path, b'{"new": true}')
        self.assertEqual(self.path.read_bytes(), b'{"previous": true}')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_read_ledger_and_storage_use_atomic_writes(self):
        with patch.object(read_store, "READ_FILE", self.path):
            read_store._local_save({"https://example.com": "today"})
            self.assertEqual(read_store._local_load(), {"https://example.com": "today"})
        with patch.object(storage, "DATA_DIR", self.path.parent):
            storage._local_write_bytes("state.json", b"updated")
            self.assertEqual(storage._local_read_bytes("state.json"), b"updated")


if __name__ == "__main__":
    unittest.main()
