import base64
import tempfile
import unittest
from pathlib import Path

from core.assets import AssetStore, normalize_layout
from core.config import PluginConfig

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lK3VAAAAAElFTkSuQmCC"
)


class FakeUpload:
    def __init__(self, filename="sprite.png", data=PNG):
        self.filename = filename
        self.content_type = "image/png"
        self.data = data

    async def save(self, target, max_bytes=None):
        Path(target).write_bytes(self.data)
        return len(self.data)


class AssetStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = PluginConfig({"background_file": "bg1.jpg"})
        self.store = AssetStore(self.config, Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults(self):
        state = self.store.state()
        self.assertEqual(state["active"], "builtin")
        self.assertEqual(len(state["characters"]), 1)
        self.assertTrue(state["characters"][0]["builtin"])
        self.assertGreaterEqual(len(state["backgrounds"]), 1)

    def test_create_and_layout(self):
        profile = self.store.create("我的角色")
        self.assertEqual(self.store.active().id, profile.id)
        self.store.save_layout(profile.id, {"left": 40, "top": -10, "height": 800, "max_width": 50})
        restored = self.store.get(profile.id)
        self.assertEqual(restored.layout["left"], 40)
        self.assertEqual(restored.layout["height"], 800)

    def test_upload_sprite_and_resolve(self):
        import asyncio

        profile = self.store.create("角色")
        asyncio.run(self.store.save_sprite(profile.id, "笑", FakeUpload()))
        restored = self.store.get(profile.id)
        self.assertIn("happy", restored.sprites)
        path = self.store.resolve_sprite(restored, "笑")
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

    def test_upload_background(self):
        import asyncio

        name = asyncio.run(self.store.save_background(FakeUpload("bg.png")))
        self.assertTrue(name.startswith("custom/"))
        self.assertIsNotNone(self.store.resolve_background(name))
        self.assertIn(name, [item["name"] for item in self.store.list_backgrounds()])

    def test_share_sprite_between_emotions(self):
        import asyncio

        profile = self.store.create("角色")
        asyncio.run(self.store.save_sprite(profile.id, "happy", FakeUpload()))
        restored = self.store.get(profile.id)
        filename = restored.sprites["happy"]
        self.store.bind_sprite(profile.id, "angry", filename)
        restored = self.store.get(profile.id)
        self.assertEqual(restored.sprites["angry"], filename)
        self.assertEqual(
            self.store.resolve_sprite(restored, "生气"),
            self.store.resolve_sprite(restored, "笑"),
        )

    def test_builtin_emotion_mapping(self):
        profile = self.store.builtin_profile()
        self.assertIn("teary.webp", self.store.resolve_sprite(profile, "sad").name)
        self.assertIn("blank.webp", self.store.resolve_sprite(profile, "shy").name)
        self.assertIn("frown.webp", self.store.resolve_sprite(profile, "tired").name)
        self.assertIn("blank.webp", self.store.resolve_sprite(profile, "worried").name)
        self.assertIn("blank.webp", self.store.resolve_sprite(profile, "moved").name)
        self.assertIn("whale_girl_moe.webp", self.store.resolve_sprite(profile, "calm").name)
        self.assertIn("frown.webp", self.store.resolve_sprite(profile, "confused").name)
        self.assertIn("frown.webp", self.store.resolve_sprite(profile, "indifferent").name)
        self.assertIn("endure.webp", self.store.resolve_sprite(profile, "scared").name)

    def test_builtin_cannot_upload_or_delete(self):
        import asyncio

        with self.assertRaises(ValueError):
            asyncio.run(self.store.save_sprite("builtin", "笑", FakeUpload()))
        with self.assertRaises(ValueError):
            self.store.delete("builtin")

    def test_bad_asset_is_rejected(self):
        import asyncio

        profile = self.store.create("角色")
        with self.assertRaises(ValueError):
            asyncio.run(self.store.save_sprite(profile.id, "笑", FakeUpload("x.png", b"not an image")))

    def test_layout_clamped(self):
        layout = normalize_layout({"left": 999, "top": -9999, "height": 1, "max_width": 999})
        self.assertEqual(layout["left"], 100)
        self.assertEqual(layout["top"], -400)
        self.assertEqual(layout["height"], 120)
        self.assertEqual(layout["max_width"], 100)

    def test_delete_custom(self):
        profile = self.store.create("角色")
        self.store.delete(profile.id)
        self.assertIsNone(self.store.get(profile.id))
        self.assertEqual(self.store.active().id, "builtin")


if __name__ == "__main__":
    unittest.main()
