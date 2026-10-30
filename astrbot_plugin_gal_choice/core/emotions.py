# SPDX-License-Identifier: AGPL-3.0-or-later
"""FishAudio emotion catalog and visual-sprite grouping.

FishAudio supports many emotion tags.  A visual novel character usually has
far fewer sprites, so every tag is mapped to one of a small set of visual
groups.  Multiple tags can therefore share one sprite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_STRIP = re.compile(r"[\[\]\(\)\{\}\s_\-]+")


@dataclass(frozen=True)
class EmotionGroup:
    id: str
    label: str
    tag: str
    tags: tuple[str, ...]
    aliases: tuple[str, ...] = ()


def _g(id, label, tag, tags, aliases=()):
    return EmotionGroup(id, label, tag, tuple(tags), tuple(aliases))


GROUPS: tuple[EmotionGroup, ...] = (
    _g(
        "happy",
        "开心",
        "happy",
        ("happy", "satisfied", "delighted", "optimistic"),
        ("笑", "高兴", "快乐", "愉快", "满意", "乐观"),
    ),
    _g(
        "excited",
        "兴奋",
        "excited",
        ("excited",),
        ("激动", "兴奋", "热情", "enthusiastic", "ecstatic"),
    ),
    _g(
        "calm",
        "平静",
        "calm",
        ("calm", "relaxed"),
        ("冷静", "平静", "放松", "neutral", "中性", "忍耐", "耐心"),
    ),
    _g(
        "sad",
        "难过",
        "sad",
        ("sad", "unhappy", "depressed", "disappointed", "regretful", "pessimistic", "lonely"),
        ("悲伤", "难过", "失落", "沮丧", "抑郁", "遗憾", "孤独", "委屈"),
    ),
    _g(
        "angry",
        "生气",
        "angry",
        ("angry", "upset", "frustrated"),
        ("愤怒", "生气", "恼火", "烦躁", "不满", "气鼓鼓"),
    ),
    _g(
        "surprised",
        "惊讶",
        "surprised",
        ("surprised",),
        ("吃惊", "震惊", "意外", "shocked", "amazed"),
    ),
    _g(
        "shy",
        "害羞",
        "embarrassed",
        ("embarrassed", "guilty", "ashamed"),
        ("害羞", "脸红", "羞耻", "内疚", "愧疚", "不好意思", "shy"),
    ),
    _g(
        "scared",
        "害怕",
        "scared",
        ("scared", "hysterical"),
        ("害怕", "恐惧", "惊恐", "惊慌", "afraid", "terrified"),
    ),
    _g(
        "worried",
        "担心",
        "worried",
        ("worried", "nervous", "anxious", "uncertain"),
        ("担心", "焦虑", "紧张", "不安", "忧虑", "皱眉", "nervous"),
    ),
    _g(
        "tired",
        "疲惫",
        "resigned",
        ("resigned",),
        ("疲惫", "累", "疲倦", "无奈", "认命", "摆烂", "tired"),
    ),
    _g(
        "gentle",
        "温柔",
        "compassionate",
        ("compassionate", "empathetic", "sympathetic", "grateful"),
        ("温柔", "体贴", "同情", "感激", "感动", "亲切", "gentle", "kind"),
    ),
    _g(
        "proud",
        "得意",
        "proud",
        ("proud", "confident", "determined"),
        ("得意", "骄傲", "自信", "坚定", "smug", "自信满满"),
    ),
    _g(
        "confused",
        "困惑",
        "confused",
        ("confused", "doubtful"),
        ("困惑", "疑惑", "不解", "迷茫", "puzzled", "doubt"),
    ),
    _g(
        "indifferent",
        "无语",
        "indifferent",
        ("indifferent", "bored"),
        ("无语", "冷漠", "无聊", "无所谓", "淡定", "bored"),
    ),
    _g(
        "teasing",
        "坏笑",
        "sarcastic",
        ("sarcastic", "jealous", "envious"),
        ("坏笑", "调侃", "戏谑", "嘲讽", "吃醋", "嫉妒", "teasing", "smug"),
    ),
    _g(
        "moved",
        "感动",
        "moved",
        ("moved", "hopeful", "nostalgic"),
        ("感动", "怀念", "怀旧", "充满希望", "touched"),
    ),
    _g(
        "disgusted",
        "厌恶",
        "disgusted",
        ("disgusted", "disdainful", "contemptuous"),
        ("厌恶", "嫌弃", "鄙视", "轻蔑", "恶心", "disgust"),
    ),
    _g(
        "curious",
        "好奇",
        "curious",
        ("curious",),
        ("好奇", "感兴趣", "探究", "interested"),
    ),
)

GROUP_BY_ID = {group.id: group for group in GROUPS}
EMOTION_IDS = tuple(group.id for group in GROUPS)
DEFAULT_GROUP = "calm"

FISH_TAGS = tuple(
    tag
    for group in GROUPS
    for tag in group.tags
)

_ALIASES: dict[str, str] = {}


def _normalize(value: str) -> str:
    return _STRIP.sub("", str(value or "").strip().lower())


for _group in GROUPS:
    for _key in (_group.id, _group.label, _group.tag, *_group.tags, *_group.aliases):
        _ALIASES.setdefault(_normalize(_key), _group.id)
# A few common aliases that do not belong to a single FishAudio tag.
for _key, _group_id in {
    "开心": "happy",
    "微笑": "happy",
    "笑容": "happy",
    "生气": "angry",
    "愤怒": "angry",
    "惊讶": "surprised",
    "吃惊": "surprised",
    "害羞": "shy",
    "难过": "sad",
    "悲伤": "sad",
    "平静": "calm",
    "忍耐": "calm",
    "温柔": "gentle",
    "得意": "proud",
    "无语": "indifferent",
    "坏笑": "teasing",
    "感动": "moved",
    "厌恶": "disgusted",
    "好奇": "curious",
}.items():
    _ALIASES[_normalize(_key)] = _group_id


def group_for(value: str) -> str:
    """Return the visual sprite group for a Chinese label or FishAudio tag."""
    return _ALIASES.get(_normalize(value), DEFAULT_GROUP)


def known_emotion(value: str) -> bool:
    return _normalize(value) in _ALIASES


def group(value: str) -> EmotionGroup:
    return GROUP_BY_ID.get(group_for(value), GROUP_BY_ID[DEFAULT_GROUP])


def tag_for(value: str) -> str:
    """Return a valid FishAudio tag for the model's emotion value."""
    normalized = _normalize(value)
    if normalized in FISH_TAGS:
        return normalized
    return group(value).tag


def tag_marker(value: str) -> str:
    return f"[{tag_for(value)}]"


def emotion_groups() -> list[dict]:
    return [
        {
            "id": item.id,
            "label": item.label,
            "tag": item.tag,
            "tags": list(item.tags),
        }
        for item in GROUPS
    ]


def emotion_labels() -> str:
    return "、".join(item.label for item in GROUPS)


def all_tags_text() -> str:
    return ", ".join(FISH_TAGS)
