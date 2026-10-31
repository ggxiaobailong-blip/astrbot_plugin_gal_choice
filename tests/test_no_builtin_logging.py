import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LoggerImportTest(unittest.TestCase):
    def test_no_builtin_logging_imports(self):
        offenders = []
        for path in ROOT.rglob("*.py"):
            if "__pycache__" in path.parts or path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            if "import logging" in text or "logging.getLogger" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertFalse(offenders, f"use astrbot.api.logger instead: {offenders}")
