import unittest

from core.script import brief, fallback_outline, parse_outline


class ScriptTest(unittest.TestCase):
    def test_parse_and_brief(self):
        script = parse_outline(
            '{"title":"雨夜","genre":"悬疑","setting":"车站","premise":"找回失物",'
            '"acts":6,"branches":[{"id":"heart","name":"相信她","color":"pink"}],'
            '"endings":[{"id":"true","name":"真结局","condition":"好感高"}]}'
        )
        self.assertEqual(script["title"], "雨夜")
        self.assertEqual(script["acts"], 6)
        text = brief(script, 5)
        self.assertIn("自然到达", text)
        self.assertIn("真结局", text)

    def test_fallback(self):
        script = fallback_outline("校园")
        self.assertEqual(script["acts"], 6)
        self.assertIn("校园", script["setting"])
