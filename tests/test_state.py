import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from core.state import Session, SessionStore


class StateTest(unittest.TestCase):
    def test_gal_idle_expiry(self):
        store = SessionStore(None, idle_seconds=60, option_ttl=30)
        session = store.get_or_create("a")
        session.mode = "gal"
        session.touch()
        self.assertIsNotNone(store.get("a"))
        session.updated_at = time.time() - 61
        self.assertIsNone(store.get("a"))

    def test_option_ttl(self):
        store = SessionStore(None, idle_seconds=600, option_ttl=30)
        session = store.get_or_create("a")
        session.options = ["A", "B"]
        session.updated_at = time.time() - 31
        self.assertIsNone(store.get("a"))

    def test_gal_options_expire_but_mode_stays(self):
        store = SessionStore(None, idle_seconds=600, option_ttl=30)
        session = store.get_or_create("a")
        session.mode = "gal"
        session.options = ["A", "B"]
        session.options_at = time.time() - 31
        session.touch()
        restored = store.get("a")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.mode, "gal")
        self.assertEqual(restored.options, [])

    def test_remove(self):
        store = SessionStore(None)
        store.get_or_create("a")
        store.remove("a")
        self.assertIsNone(store.get("a"))

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            store = SessionStore(path, idle_seconds=600, option_ttl=300)
            session = store.get_or_create("a")
            session.mode = "gal"
            session.options = ["去海边", "去山里"]
            session.history = ["第 1 幕：选了「去海边」"]
            asyncio.run(store.save())
            self.assertTrue(path.exists())
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("a", raw)

            loaded = SessionStore(path, idle_seconds=600, option_ttl=300)
            restored = loaded.get("a")
            self.assertIsNotNone(restored)
            self.assertEqual(restored.mode, "gal")
            self.assertEqual(restored.options, ["去海边", "去山里"])
            self.assertEqual(restored.history, ["第 1 幕：选了「去海边」"])

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sessions.json"
            path.write_text("{not json", encoding="utf-8")
            store = SessionStore(path)
            self.assertEqual(len(store), 0)


if __name__ == "__main__":
    unittest.main()
