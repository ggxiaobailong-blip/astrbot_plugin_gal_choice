import json
import unittest
from pathlib import Path

from core.config import DEFAULTS, PluginConfig, safe_asset


class ConfigTest(unittest.TestCase):
    def test_schema_defaults_match_code(self):
        root = Path(__file__).resolve().parent.parent
        schema = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema), set(DEFAULTS))
        for key, default in DEFAULTS.items():
            with self.subTest(key=key):
                self.assertEqual(schema[key]["default"], default)

    def test_words_are_deduped(self):
        config = PluginConfig({"mode_on_words": "进入gal模式, 进入gal模式，gal模式"})
        self.assertEqual(config.words("mode_on_words"), ["进入gal模式", "gal模式"])

    def test_empty_string_falls_back(self):
        config = PluginConfig({"bot_label": ""})
        self.assertEqual(config.str("bot_label", "小鲸鱼"), "小鲸鱼")

    def test_safe_asset_rejects_traversal(self):
        root = Path(__file__).resolve().parent.parent
        self.assertIsNone(safe_asset(root / "assets", "../../main.py"))
        self.assertIsNotNone(safe_asset(root / "assets", "whale_girl_moe.webp"))


if __name__ == "__main__":
    unittest.main()
