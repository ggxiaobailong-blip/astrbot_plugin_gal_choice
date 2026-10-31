# SPDX-License-Identifier: AGPL-3.0-or-later
"""Affection stages and the eight flat mood faces used by the HUD."""

from __future__ import annotations

from .emotions import group_for

MIN_AFFECTION = 0
MAX_AFFECTION = 100
DEFAULT_AFFECTION = 50

STAGES: tuple[tuple[int, int, str, str], ...] = (
    (0, 20, "冷淡", "#8b9bb4"),
    (21, 40, "不耐烦", "#d99a5b"),
    (41, 60, "平和", "#6fb6ff"),
    (61, 80, "亲近", "#ef9cc3"),
    (81, 100, "喜欢", "#ff6f9f"),
)

GROUP_TO_MOOD = {
    "calm": "calm",
    "gentle": "calm",
    "tired": "calm",
    "happy": "happy",
    "excited": "happy",
    "proud": "happy",
    "sad": "sad",
    "worried": "sad",
    "scared": "sad",
    "angry": "angry",
    "disgusted": "disgust",
    "indifferent": "disgust",
    "teasing": "disgust",
    "shy": "shy",
    "moved": "shy",
    "surprised": "surprised",
    "curious": "surprised",
    "confused": "confused",
}

MOODS: dict[str, dict] = {
    "calm": {"label": "平静", "color": "#f2e7d5"},
    "happy": {"label": "开心", "color": "#ffd3e2"},
    "sad": {"label": "难过", "color": "#cfe4ff"},
    "angry": {"label": "生气", "color": "#ffd0c8"},
    "disgust": {"label": "厌恶", "color": "#e5d2ff"},
    "shy": {"label": "害羞", "color": "#ffe0d2"},
    "surprised": {"label": "惊讶", "color": "#ffe7b3"},
    "confused": {"label": "困惑", "color": "#dcd7ff"},
}

_FACE_BODIES = {
    "calm": """
      <circle cx="11" cy="14" r="1.4" fill="#3b302b"/><circle cx="21" cy="14" r="1.4" fill="#3b302b"/>
      <path d="M11 21q5 2 10 0" stroke="#3b302b" stroke-width="1.8" fill="none" stroke-linecap="round"/>
    """,
    "happy": """
      <path d="M8 13q3-3 6 0M18 13q3-3 6 0" stroke="#3b302b" stroke-width="1.7" fill="none" stroke-linecap="round"/>
      <path d="M10 20q6 7 12 0" stroke="#3b302b" stroke-width="1.9" fill="none" stroke-linecap="round"/>
    """,
    "sad": """
      <path d="M8 14q3-3 6 0M18 14q3-3 6 0" stroke="#3b302b" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M11 23q5-5 10 0" stroke="#3b302b" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <path d="M22 16q2 2 0 4" stroke="#6f9fd8" stroke-width="1.8" fill="none" stroke-linecap="round"/>
    """,
    "angry": """
      <path d="M8 11l5 2M24 11l-5 2" stroke="#3b302b" stroke-width="1.5" stroke-linecap="round"/>
      <circle cx="11" cy="16" r="1.3" fill="#3b302b"/><circle cx="21" cy="16" r="1.3" fill="#3b302b"/>
      <path d="M11 23q5-4 10 0" stroke="#3b302b" stroke-width="1.8" fill="none" stroke-linecap="round"/>
    """,
    "disgust": """
      <path d="M8 14h6M18 14h6" stroke="#3b302b" stroke-width="1.7" stroke-linecap="round"/>
      <path d="M12 21q2-2 4 0t4 0" stroke="#3b302b" stroke-width="1.8" fill="none" stroke-linecap="round"/>
    """,
    "shy": """
      <path d="M8 14q3-3 6 0M18 14q3-3 6 0" stroke="#3b302b" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <path d="M12 21q4 2 8 0" stroke="#3b302b" stroke-width="1.8" fill="none" stroke-linecap="round"/>
      <ellipse cx="7" cy="20" rx="3" ry="1.6" fill="#ec9eb7" opacity=".8"/>
      <ellipse cx="25" cy="20" rx="3" ry="1.6" fill="#ec9eb7" opacity=".8"/>
    """,
    "surprised": """
      <circle cx="11" cy="14" r="2" fill="#3b302b"/><circle cx="21" cy="14" r="2" fill="#3b302b"/>
      <ellipse cx="16" cy="22" rx="3" ry="2" fill="none" stroke="#3b302b" stroke-width="1.7"/>
    """,
    "confused": """
      <path d="M8 11q3 2 6 0M18 14q3-3 6 0" stroke="#3b302b" stroke-width="1.6" fill="none" stroke-linecap="round"/>
      <circle cx="11" cy="15" r="1.3" fill="#3b302b"/><circle cx="21" cy="15" r="1.3" fill="#3b302b"/>
      <path d="M11 22q3-2 5 0t5-1" stroke="#3b302b" stroke-width="1.7" fill="none" stroke-linecap="round"/>
    """,
}


def clamp(value: int) -> int:
    return max(MIN_AFFECTION, min(MAX_AFFECTION, int(value)))


def stage_for(value: int) -> dict:
    value = clamp(value)
    for low, high, label, color in STAGES:
        if low <= value <= high:
            return {
                "low": low,
                "high": high,
                "label": label,
                "color": color,
                "value": value,
                "percent": value,
            }
    return {"low": 0, "high": 20, "label": "冷淡", "color": "#8b9bb4", "value": value, "percent": value}


def mood_for(value: str) -> str:
    group = group_for(value or "")
    return GROUP_TO_MOOD.get(group, "calm")


def mood_label(mood: str) -> str:
    return MOODS.get(mood, MOODS["calm"])["label"]


def mood_color(mood: str) -> str:
    return MOODS.get(mood, MOODS["calm"])["color"]


def mood_svg(mood: str) -> str:
    mood = mood if mood in MOODS else "calm"
    color = mood_color(mood)
    body = _FACE_BODIES[mood]
    return (
        '<svg viewBox="0 0 32 32" class="mood-svg">'
        f'<circle cx="16" cy="16" r="13.5" fill="{color}"/>'
        f"{body}</svg>"
    )


def tone_hint(value: int) -> str:
    value = clamp(value)
    if value >= 81:
        return (
            "当前好感：喜欢。语气要明显亲近、黏人，会主动关心玩家、想多待一会儿；"
            "可以撒娇，但不要威胁、操控或让玩家内疚。"
        )
    if value >= 61:
        return "当前好感：亲近。语气温柔、愿意分享，会主动接话和关心玩家，但还不到黏人的程度。"
    if value >= 41:
        return "当前好感：平和。像熟悉的朋友，自然聊天，不刻意讨好也不冷淡。"
    if value >= 21:
        return "当前好感：不耐烦。语气开始敷衍、带一点刺，回答更短，但仍会继续对话。"
    return (
        "当前好感：冷淡。语气明显不客气、疏离，能一句话说完就不多说；"
        "不要辱骂，也不要主动示好。"
    )
