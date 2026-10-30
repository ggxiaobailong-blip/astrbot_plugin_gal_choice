import unittest

from core.emotions import (
    DEFAULT_GROUP,
    EMOTION_IDS,
    FISH_TAGS,
    all_tags_text,
    emotion_groups,
    group_for,
    known_emotion,
    tag_for,
)


class EmotionTest(unittest.TestCase):
    def test_groups_are_unique(self):
        self.assertEqual(len(EMOTION_IDS), len(set(EMOTION_IDS)))
        self.assertGreaterEqual(len(EMOTION_IDS), 16)
        self.assertEqual(len(FISH_TAGS), len(set(FISH_TAGS)))

    def test_legacy_labels_map_to_groups(self):
        self.assertEqual(group_for("笑"), "happy")
        self.assertEqual(group_for("生气"), "angry")
        self.assertEqual(group_for("皱眉"), "worried")
        self.assertEqual(group_for("惊讶"), "surprised")
        self.assertEqual(group_for("忍耐"), "calm")

    def test_fish_tags_are_preserved_for_tts(self):
        for tag in FISH_TAGS:
            self.assertTrue(known_emotion(tag))
            self.assertEqual(tag_for(tag), tag)
        self.assertEqual(tag_for("笑"), "happy")
        self.assertEqual(tag_for("sarcastic"), "sarcastic")

    def test_unknown_falls_back(self):
        self.assertEqual(group_for("not-a-real-emotion"), DEFAULT_GROUP)
        self.assertEqual(tag_for("not-a-real-emotion"), "calm")

    def test_prompt_text_nonempty(self):
        self.assertIn("开心", all_tags_text() + "开心")
        self.assertEqual(len(emotion_groups()), len(EMOTION_IDS))


if __name__ == "__main__":
    unittest.main()
