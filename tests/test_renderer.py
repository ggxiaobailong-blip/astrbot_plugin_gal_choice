import json
import tempfile
import unittest
from pathlib import Path

from core.assets import AssetStore
from core.config import PluginConfig
from core.renderer import Renderer
from core.state import Session


class RendererTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = PluginConfig({"background_file": "bg1.jpg"})
        self.assets = AssetStore(self.config, Path(self.tmp.name))
        self.renderer = Renderer(self.config, self.assets)
        self.session = Session(key="test")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **overrides):
        values = {
            "session": self.session,
            "quote": "最近总是睡不好，有没有什么办法？",
            "options": ["先从作息调整开始", "试试睡前放松练习", "聊聊压力和心事"],
            "say": "先别急，我们一个一个来试嘛。",
            "emotion": "笑",
            "speaker": "阿岚",
            "user_id": "10001",
        }
        values.update(overrides)
        return self.renderer.build(**values)

    def test_build_shape(self):
        template, data = self.build()
        self.assertIn("{{ say|e }}", template)
        self.assertIn("object-fit: contain", template)
        self.assertIn("char-box", template)
        self.assertEqual(data["speaker"], "阿岚")
        self.assertEqual(len(data["options"]), 4)
        self.assertEqual(data["options"][-1]["letter"], "0")
        self.assertTrue(data["options"][-1]["cls"])

    def test_custom_layout_is_used(self):
        profile = self.assets.create("自定义")
        self.assets.save_layout(profile.id, {"left": 22, "top": 44, "height": 700, "max_width": 48})
        _, data = self.build()
        self.assertEqual(data["char_left"], 22)
        self.assertEqual(data["char_top"], 44)
        self.assertEqual(data["char_height"], 700)
        self.assertEqual(data["char_max_width"], 48)

    def test_preview_layout_override(self):
        _, data = self.build(layout={"left": 12, "top": 100, "height": 600, "max_width": 30})
        self.assertEqual(data["char_left"], 12)
        self.assertEqual(data["char_top"], 100)
        self.assertEqual(data["char_height"], 600)
        self.assertEqual(data["char_max_width"], 30)

    def test_long_say_shrinks_font(self):
        _, data = self.build(say="这是一段非常长的台词" * 8)
        self.assertLess(data["say_font"], 26)
        self.assertTrue(data["say"].endswith("…"))

    def test_custom_free_hint_fits(self):
        config = PluginConfig(
            {
                "background_file": "bg1.jpg",
                "free_option_hint": "没有想选的？直接把你的想法打在这里，我会顺着你的话说下去",
            }
        )
        renderer = Renderer(
            config, AssetStore(config, Path(self.tmp.name) / "custom-free")
        )
        _, data = renderer.build(
            session=self.session,
            quote="q",
            options=["a", "b"],
            say="s",
            emotion="",
            speaker="p",
            user_id="1",
        )
        self.assertTrue(data["options"][-1]["text"].endswith("…"))

    def test_path_traversal_rejected(self):
        config = PluginConfig(
            {
                "emotion_map": {"笑": "../../secret.webp"},
                "emotion_default_file": "whale_girl_moe.webp",
            }
        )
        renderer = Renderer(
            config, AssetStore(config, Path(self.tmp.name) / "traversal")
        )
        path = renderer.resolve_character("笑")
        self.assertIsNotNone(path)
        self.assertIn("whale_girl_moe.webp", path.name)

    def test_avatar_disabled(self):
        config = PluginConfig({"avatar_enabled": False})
        renderer = Renderer(
            config, AssetStore(config, Path(self.tmp.name) / "avatar")
        )
        self.assertEqual(renderer.avatar_url("10001"), "")

    def test_data_is_json_serializable(self):
        _, data = self.build()
        json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
