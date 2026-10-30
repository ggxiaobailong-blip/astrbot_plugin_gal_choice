# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parsing helpers for the GalGame reply format and for user choices.

Everything in this module is pure Python and unit-testable without AstrBot.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .emotions import known_emotion

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

_EMO_RE = re.compile(r"<emo>(.*?)</emo>", re.S | re.I)
_SAY_RE = re.compile(r"<say>(.*?)</say>", re.S | re.I)
_OPT_RE = re.compile(r"<opt>(.*?)</opt>", re.S | re.I)
_KNOWN_TAG_RE = re.compile(r"</?(?:emo|say|opt|narration|narr)\b[^>]*>", re.I)
_ANY_TAG_RE = re.compile(r"</?[a-zA-Z][^>]{0,40}>")
_CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*\s*\n?")
_INVIS_RE = re.compile(r"\[(?:MSG_ID|引用|CQ)[^\]]*\]|[\u200b\u200c\u200d\ufeff]")
_LIST_RE = re.compile(r"^\s*(?:[A-Za-z]|[0-9]{1,2})\s*[.、)．:：]\s*(.+)$")
_BULLET_RE = re.compile(r"^\s*[-*•·]\s+(.+)$")
_TRAILING_PUNCT = "，,、。；;：: "
_FREE_WORDS = {"0", "自由输入", "自由", "自己输入", "其他", "自己说", "随便说", "自定义"}

_EMOTION_ALIASES = {
    "笑": "笑",
    "开心": "笑",
    "高兴": "笑",
    "快乐": "笑",
    "微笑": "笑",
    "生气": "生气",
    "愤怒": "生气",
    "怒": "生气",
    "皱眉": "皱眉",
    "为难": "皱眉",
    "困扰": "皱眉",
    "惊讶": "惊讶",
    "吃惊": "惊讶",
    "震惊": "惊讶",
    "忍耐": "忍耐",
    "无奈": "忍耐",
    "叹气": "忍耐",
}


@dataclass
class GalTurn:
    say: str = ""
    options: list[str] = field(default_factory=list)
    emotion: str = ""
    raw: str = ""


@dataclass
class OptionMatch:
    index: int | None = None
    score: float = 0.0
    ambiguous: bool = False
    free: bool = False
    second_index: int | None = None


def normalize_emotion(value: str) -> str:
    text = re.sub(r"\s+", "", value or "")
    text = text.strip("[]()（）【】")
    if not text:
        return ""
    if text in _EMOTION_ALIASES:
        return _EMOTION_ALIASES[text]
    for key, mapped in _EMOTION_ALIASES.items():
        if key and key in text:
            return mapped
    if known_emotion(text):
        return text
    for token in re.split(r"[,，、/|]+", text):
        if token and known_emotion(token):
            return token
    return ""


def clean_message(text: str) -> str:
    return _INVIS_RE.sub("", text or "").strip()


def _strip_code_fences(text: str) -> str:
    text = _CODE_FENCE_RE.sub("", text or "")
    text = text.replace("```", "")
    lines = text.splitlines()
    if lines and lines[0].strip().lower() in {"html", "xml", "text", "json"}:
        lines = lines[1:]
    return "\n".join(lines)


def _clean_say(text: str) -> str:
    text = _KNOWN_TAG_RE.sub("", text or "")
    text = _ANY_TAG_RE.sub("", text)
    text = text.replace("<", "＜").replace(">", "＞")
    text = re.sub(r"[*_`#>~|]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("「」『』\"'“”‘’")
    return text


def clean_option(text: str) -> str:
    text = _KNOWN_TAG_RE.sub("", text or "")
    text = _ANY_TAG_RE.sub("", text)
    text = text.replace("<", "＜").replace(">", "＞")
    text = re.sub(r"^\s*(?:[A-Za-z]|[0-9]{1,2})\s*[.、)．:：]\s*", "", text)
    text = re.sub(r"^\s*[-*•·]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("「」『』\"'“”‘’")
    text = text.rstrip(_TRAILING_PUNCT)
    return text


def _char_width(ch: str) -> float:
    if ch == "\u200b":
        return 0.0
    code = ord(ch)
    if code >= 0x1F000:  # emoji
        return 1.0
    if code > 0x2E80:  # CJK and full-width punctuation
        return 1.0
    if ch in "ilI.,'!|:;":
        return 0.3
    return 0.55


def display_units(text: str) -> float:
    return sum(_char_width(ch) for ch in (text or ""))


def fit_text(text: str, max_units: float) -> str:
    """Truncate by approximate display width (CJK=1, ASCII=0.55)."""
    text = (text or "").strip()
    if not text or max_units <= 0:
        return ""
    width = 0.0
    out: list[str] = []
    for ch in text:
        cw = _char_width(ch)
        if width + cw > max_units:
            head = "".join(out).rstrip(_TRAILING_PUNCT)
            return (head or "".join(out)) + "…"
        width += cw
        out.append(ch)
    return text


def _dedupe(options: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for option in options:
        key = option.casefold()
        if option and key not in seen:
            seen.add(key)
            out.append(option)
    return out


def _parse_list_options(text: str) -> list[str]:
    options: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        match = _LIST_RE.match(line) or _BULLET_RE.match(line)
        if match:
            option = clean_option(match.group(1))
            if option and len(option) <= 80:
                options.append(option)
    if len(options) < 2:
        return []
    return options


def parse_gal_reply(text: str, option_max_units: float = 16.0) -> GalTurn:
    """Parse ``<emo>/<say>/<opt>`` with tolerant fallbacks for list replies."""
    raw = _strip_code_fences(text or "").strip()
    if not raw:
        return GalTurn(raw=text or "")

    # Some models ignore the tag format and return JSON instead.
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            options = payload.get("options") or payload.get("choices") or []
            if isinstance(options, list):
                options = [
                    clean_option(
                        str(
                            item.get("text") or item.get("label") or ""
                            if isinstance(item, dict)
                            else item
                        )
                    )
                    for item in options
                    if (isinstance(item, dict) or str(item).strip())
                ]
                say = _clean_say(str(payload.get("say") or payload.get("text") or ""))
                emotion = normalize_emotion(str(payload.get("emotion") or payload.get("emo") or ""))
                options = [fit_text(item, option_max_units) for item in _dedupe(options)][:4]
                if say or len(options) >= 2:
                    return GalTurn(say=say, options=options, emotion=emotion, raw=text or "")

    emotion = ""
    emo_match = _EMO_RE.search(raw)
    if emo_match:
        emotion = normalize_emotion(emo_match.group(1))
    raw = _EMO_RE.sub("", raw)

    say = ""
    say_match = _SAY_RE.search(raw)
    if say_match:
        say = _clean_say(say_match.group(1))
    raw = _SAY_RE.sub("", raw)

    options = [clean_option(item) for item in _OPT_RE.findall(raw)]
    options = [item for item in options if item]
    raw = _OPT_RE.sub("", raw)

    if len(options) < 2:
        listed = _parse_list_options(raw)
        if listed:
            if not say:
                first_list = min(
                    (m.start() for m in (_LIST_RE.search(raw), _BULLET_RE.search(raw)) if m),
                    default=None,
                )
                if first_list is not None:
                    say = _clean_say(raw[:first_list])
            options = listed

    if not say:
        say = _clean_say(raw)

    options = _dedupe(options)
    options = [fit_text(item, option_max_units) for item in options][:4]
    options = [item for item in options if item]

    if not options:
        say = _clean_say(_ANY_TAG_RE.sub("", text or ""))
    return GalTurn(say=say, options=options, emotion=emotion, raw=text or "")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def normalize_phrase(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip()
    text = re.sub(r"[\s。.!！~～,，、;；:：]+$", "", text)
    text = re.sub(r"(?:吧|呀|啊|哦|嘛|呢)$", "", text)
    return text.casefold()


def phrase_hit(text: str, words: list[str] | tuple[str, ...]) -> bool:
    normalized = normalize_phrase(text)
    if not normalized:
        return False
    return any(normalized == normalize_phrase(word) for word in words if word)


_EXIT_MARKERS = ("退出", "关闭", "结束", "不玩", "别玩", "停止", "quit", "exit")
_START_MARKERS = ("启动", "开始", "进入", "开启", "打开", "切换", "来玩", "玩")
_QUESTION_WORDS = ("什么", "怎么", "如何", "为什么", "为啥", "吗", "哪", "谁", "是不是")
_EXIT_NEGATION = re.compile(r"(不要|别|不想|不用|无需)(?:退出|关闭|结束|停止)")


def _intent_text(text: str) -> str:
    return normalize_text(text)


def _is_question(text: str) -> bool:
    raw = unicodedata.normalize("NFKC", text or "").casefold()
    return "?" in raw or "？" in raw or any(word in raw for word in _QUESTION_WORDS)


def is_exit_intent(text: str, words: list[str] | tuple[str, ...] = ()) -> bool:
    """Fuzzy exit: 结束gal / 退出 / 关闭 / 不玩了 all count."""
    raw = unicodedata.normalize("NFKC", text or "").casefold()
    normalized = _intent_text(text)
    if not normalized:
        return False
    if _EXIT_NEGATION.search(raw):
        return False
    if any(_intent_text(word) and _intent_text(word) in normalized for word in words):
        return True
    if not any(marker in normalized for marker in _EXIT_MARKERS):
        return False
    # Bare short commands are unambiguous; otherwise require "gal".
    return "gal" in normalized or len(normalized) <= 8


def is_start_intent(text: str, words: list[str] | tuple[str, ...] = ()) -> bool:
    """Fuzzy start: gal启动 / 启动gal / 来玩gal / gal模式 all count.

    Exit intents win first, so "结束gal" never starts a new session.
    """
    raw = unicodedata.normalize("NFKC", text or "").casefold()
    normalized = _intent_text(text)
    if not normalized:
        return False
    if is_exit_intent(text, words=()):
        return False
    if _is_question(text):
        return False
    if re.search(r"(不要|别|不想|不用|无需)(?:启动|开始|进入|开启|打开|玩)", raw):
        return False
    if any(_intent_text(word) and _intent_text(word) in normalized for word in words):
        return True
    if normalized in {"gal", "galgame"} or "gal模式" in normalized or "gal游戏" in normalized:
        return True
    return "gal" in normalized and any(marker in normalized for marker in _START_MARKERS)


def _longest_common_substring(a: str, b: str) -> int:
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    best = 0
    for ch_a in a:
        current = [0] * (len(b) + 1)
        for j, ch_b in enumerate(b, start=1):
            if ch_a == ch_b:
                current[j] = previous[j - 1] + 1
                if current[j] > best:
                    best = current[j]
        previous = current
    return best


def match_option(text: str, options: list[str]) -> OptionMatch:
    """Match a letter, a number, the free-input slot, or option wording."""
    raw = normalize_text(clean_message(text))
    if not raw:
        return OptionMatch()

    if raw in _FREE_WORDS:
        return OptionMatch(free=True)

    if len(raw) == 1:
        ch = raw.upper()
        if ch in LETTERS:
            index = LETTERS.index(ch)
            if index < len(options):
                return OptionMatch(index=index, score=1.0)
        if ch.isdigit() and 1 <= int(ch) <= len(options):
            return OptionMatch(index=int(ch) - 1, score=1.0)

    letter_match = re.match(r"^(?:选|我选|选择|我选择|点|就选|要)?([A-Z])$", raw, re.I)
    if letter_match:
        index = LETTERS.index(letter_match.group(1).upper())
        if index < len(options):
            return OptionMatch(index=index, score=1.0)

    digit_match = re.match(r"^(?:选|我选|选择|我选择|点|就选|要)?([1-9])$", raw)
    if digit_match:
        index = int(digit_match.group(1)) - 1
        if index < len(options):
            return OptionMatch(index=index, score=1.0)

    if len(raw) < 2:
        return OptionMatch()

    scored: list[tuple[float, int]] = []
    for index, option in enumerate(options):
        candidate = normalize_text(option)
        if not candidate:
            continue
        if raw == candidate:
            scored.append((1.0, index))
            continue
        if candidate in raw or raw in candidate:
            ratio = min(len(candidate), len(raw)) / max(len(candidate), len(raw))
            scored.append((0.78 + 0.17 * ratio, index))
            continue
        lcs = _longest_common_substring(raw, candidate)
        score = 0.95 * lcs / max(len(raw), len(candidate))
        ratio = SequenceMatcher(None, raw, candidate).ratio()
        score = max(score, 0.85 * ratio)
        if len(raw) >= 2 and len(candidate) >= 2:
            grams_a = {raw[i : i + 2] for i in range(len(raw) - 1)}
            grams_b = {candidate[i : i + 2] for i in range(len(candidate) - 1)}
            union = grams_a | grams_b
            if union:
                score = max(score, 0.9 * len(grams_a & grams_b) / len(union))
        scored.append((score, index))

    if not scored:
        return OptionMatch()

    scored.sort(reverse=True)
    best_score, best_index = scored[0]
    if best_score < 0.55:
        return OptionMatch()
    ambiguous = (
        len(scored) > 1
        and best_score < 0.95
        and scored[1][0] >= best_score - 0.07
    )
    second_index = scored[1][1] if ambiguous else None
    return OptionMatch(
        index=best_index,
        score=best_score,
        ambiguous=ambiguous,
        second_index=second_index,
    )


def readable_fallback(
    say: str,
    options: list[str],
    bot_label: str = "小鲸鱼",
    default_say: str = "这几个方向，你想先聊哪个？",
) -> str:
    lines = [f"{bot_label}：{_clean_say(say) or default_say}"]
    for index, option in enumerate(options):
        letter = LETTERS[index] if index < len(LETTERS) else str(index + 1)
        lines.append(f"{letter}. {_clean_say(option)}")
    lines.append("回复字母选择，或者直接说说你的想法。")
    return "\n".join(lines)
