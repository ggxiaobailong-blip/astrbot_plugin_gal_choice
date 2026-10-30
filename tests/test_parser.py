import unittest

from core.parser import (
    clean_message,
    display_units,
    fit_text,
    is_exit_intent,
    is_start_intent,
    match_option,
    parse_gal_reply,
    phrase_hit,
    readable_fallback,
)


class ParserTest(unittest.TestCase):
    def test_standard_tags(self):
        turn = parse_gal_reply(
            "<emo>笑</emo><say>今天想从哪里开始？</say>"
            "<opt>去海边</opt><opt>去山里</opt><opt>留在家里</opt>"
        )
        self.assertEqual(turn.emotion, "笑")
        self.assertEqual(turn.say, "今天想从哪里开始？")
        self.assertEqual(turn.options, ["去海边", "去山里", "留在家里"])

    def test_code_fence(self):
        turn = parse_gal_reply(
            "```xml\n<emo>惊讶</emo>\n<say>欸？</say>\n"
            "<opt>解释一下</opt><opt>先不管</opt>\n```"
        )
        self.assertEqual(turn.emotion, "惊讶")
        self.assertEqual(turn.say, "欸？")
        self.assertEqual(len(turn.options), 2)

    def test_numbered_list(self):
        turn = parse_gal_reply(
            "好呀，给你三个方向：\n1. 先休息\n2. 去散步\n3. 聊聊天"
        )
        self.assertEqual(turn.options, ["先休息", "去散步", "聊聊天"])

    def test_json_reply(self):
        turn = parse_gal_reply(
            '{"emotion": "惊讶", "say": "欸？", "options": ["解释一下", "先不管"]}'
        )
        self.assertEqual(turn.emotion, "惊讶")
        self.assertEqual(turn.say, "欸？")
        self.assertEqual(turn.options, ["解释一下", "先不管"])

    def test_emotion_alias(self):
        turn = parse_gal_reply("<emo>开心</emo><say>好耶</say><opt>继续</opt><opt>等等</opt>")
        self.assertEqual(turn.emotion, "笑")

    def test_no_options_returns_text(self):
        turn = parse_gal_reply("今天天气不错。")
        self.assertEqual(turn.options, [])
        self.assertIn("天气", turn.say)

    def test_fit_text(self):
        self.assertEqual(fit_text("abc", 10), "abc")
        self.assertTrue(fit_text("一二三四五六", 4).endswith("…"))
        self.assertEqual(display_units("一二"), 2.0)

    def test_match_letter_and_number(self):
        options = ["去海边", "去山里", "留在家里"]
        self.assertEqual(match_option("A", options).index, 0)
        self.assertEqual(match_option("2", options).index, 1)
        self.assertEqual(match_option("选C", options).index, 2)
        self.assertEqual(match_option("0", options).free, True)

    def test_match_option_text(self):
        options = ["去海边吹风", "去山里住一晚"]
        match = match_option("海边", options)
        self.assertEqual(match.index, 0)
        self.assertFalse(match.ambiguous)

    def test_ambiguous_options(self):
        options = ["去海边", "去海山"]
        match = match_option("去海", options)
        self.assertTrue(match.ambiguous)

    def test_phrase_hit_is_exact(self):
        self.assertTrue(phrase_hit("进入gal模式吧", ["进入gal模式"]))

    def test_fuzzy_start_intent(self):
        self.assertTrue(is_start_intent("gal启动！"))
        self.assertTrue(is_start_intent("启动gal！"))
        self.assertTrue(is_start_intent("来玩gal"))
        self.assertTrue(is_start_intent("gal模式"))
        self.assertFalse(is_start_intent("gal是什么"))
        self.assertFalse(is_start_intent("gal模式怎么退出"))

    def test_fuzzy_exit_intent_has_priority(self):
        self.assertTrue(is_exit_intent("结束gal"))
        self.assertTrue(is_exit_intent("gal结束"))
        self.assertTrue(is_exit_intent("不玩了"))
        self.assertTrue(is_exit_intent("退出"))
        self.assertFalse(is_exit_intent("不要结束"))
        self.assertFalse(is_start_intent("结束gal"))
        self.assertFalse(phrase_hit("gal模式是什么", ["gal模式"]))
        self.assertTrue(phrase_hit("/gal start", ["/gal start"]))

    def test_clean_message(self):
        self.assertEqual(clean_message("[MSG_ID:1]A\u200b"), "A")

    def test_fallback_has_no_tags(self):
        text = readable_fallback("<say>台词</say>", ["A", "B"])
        self.assertNotIn("<", text)
        self.assertIn("A. A", text)


if __name__ == "__main__":
    unittest.main()
