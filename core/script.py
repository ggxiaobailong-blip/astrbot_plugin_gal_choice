# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-shot story outline for a gal run, plus compact turn briefs."""

from __future__ import annotations

import json
import re

DEFAULT_ACTS = 6


def fallback_outline(setting: str = "") -> dict:
    setting = (setting or "").strip()
    return {
        "title": "未完的约定",
        "genre": "日常 / 关系",
        "setting": setting or "一个安静的傍晚，两个人在熟悉的街角重新遇见",
        "premise": "玩家和角色在一次次选择里重新靠近，最后必须面对一个不能回避的决定。",
        "acts": DEFAULT_ACTS,
        "branches": [
            {"id": "heart", "name": "靠近她", "color": "pink"},
            {"id": "reason", "name": "保持距离", "color": "blue"},
        ],
        "endings": [
            {"id": "true", "name": "真结局 · 留在这里", "condition": "好感高，并选择靠近"},
            {"id": "normal", "name": "普通结局 · 各自向前", "condition": "好感中等，或没有明确选择"},
            {"id": "bad", "name": "坏结局 · 错过", "condition": "好感低，或反复推开她"},
        ],
    }


def outline_prompt(setting: str = "") -> str:
    setting = (setting or "").strip()
    request = (
        f"玩家想要的故事类型/背景：{setting}"
        if setting
        else "玩家没有指定故事类型，请你自行决定一个适合私聊 GalGame 的题材。"
    )
    return (
        "你是一个 GalGame 剧本策划。请为一次 5~7 幕的私聊视觉小说生成开局大纲。\n"
        f"{request}\n"
        "只输出一个 JSON 对象，不要 Markdown，不要解释。字段：\n"
        "{\n"
        '  "title": "短标题",\n'
        '  "genre": "类型",\n'
        '  "setting": "时间地点和氛围",\n'
        '  "premise": "两句话以内的主线冲突，不要剧透结局",\n'
        '  "acts": 6,\n'
        '  "branches": [\n'
        '    {"id": "heart", "name": "情感方向", "color": "pink"},\n'
        '    {"id": "reason", "name": "理性方向", "color": "blue"}\n'
        "  ],\n"
        '  "endings": [\n'
        '    {"id": "true", "name": "真结局名", "condition": "达成条件"},\n'
        '    {"id": "normal", "name": "普通结局名", "condition": "达成条件"},\n'
        '    {"id": "bad", "name": "坏结局名", "condition": "达成条件"}\n'
        "  ]\n"
        "}\n"
        "要求：branches 2 个，endings 2~3 个；条件要能通过好感度、关键选择或终章选择判断；"
        "不要出现玩家没有选择的角色名；整体保持 SFW。"
    )


def parse_outline(text: str, setting: str = "") -> dict:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    try:
        payload = json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return fallback_outline(setting)
        try:
            payload = json.loads(match.group(0))
        except Exception:
            return fallback_outline(setting)
    if not isinstance(payload, dict):
        return fallback_outline(setting)
    base = fallback_outline(setting)
    for key in ("title", "genre", "setting", "premise"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            base[key] = value.strip()[:180]
    try:
        acts = int(payload.get("acts") or base["acts"])
    except (TypeError, ValueError):
        acts = base["acts"]
    base["acts"] = max(4, min(8, acts))

    branches = payload.get("branches")
    if isinstance(branches, list):
        cleaned = []
        for item in branches[:3]:
            if not isinstance(item, dict):
                continue
            bid = str(item.get("id") or "").strip()[:24]
            name = str(item.get("name") or "").strip()[:40]
            if not bid or not name:
                continue
            color = str(item.get("color") or "").strip().lower()
            if color not in {"pink", "blue"}:
                color = "pink" if len(cleaned) == 0 else "blue"
            cleaned.append({"id": bid, "name": name, "color": color})
        if cleaned:
            base["branches"] = cleaned

    endings = payload.get("endings")
    if isinstance(endings, list):
        cleaned = []
        for item in endings[:4]:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("id") or "").strip()[:24]
            name = str(item.get("name") or "").strip()[:50]
            if not eid or not name:
                continue
            cleaned.append(
                {
                    "id": eid,
                    "name": name,
                    "condition": str(item.get("condition") or "").strip()[:100],
                }
            )
        if cleaned:
            base["endings"] = cleaned
    return base


def ending_by_id(script: dict, ending_id: str) -> dict:
    for item in script.get("endings", []) if isinstance(script, dict) else []:
        if isinstance(item, dict) and str(item.get("id")) == ending_id:
            return item
    return {"id": ending_id or "normal", "name": "结局", "condition": ""}


def brief(script: dict, turn: int) -> str:
    """Compact outline for injection, without revealing endings to the player."""
    if not isinstance(script, dict) or not script:
        return ""
    acts = int(script.get("acts") or DEFAULT_ACTS)
    current = min(acts, max(1, int(turn) + 1))
    branches = "；".join(
        f'{item.get("id")}: {item.get("name")}'
        for item in script.get("branches", [])
        if isinstance(item, dict)
    )
    endings = "；".join(
        f'{item.get("id")}: {item.get("name")}'
        for item in script.get("endings", [])
        if isinstance(item, dict)
    )
    final_hint = (
        "已经接近预计篇幅。如果剧情已经自然到达可以收束的节点，可在末尾输出 "
        "<ending>结局id</ending>；如果还有未解决的冲突，就继续写，不要为了结束硬转。"
        if current >= acts
        else "按当前剧情自然推进。不要为了接近预计幕数而硬转剧情，也不要无限拖延。"
    )
    return (
        f"【本局剧本大纲｜内部使用，不要向玩家剧透】\n"
        f"标题：{script.get('title', '')}；类型：{script.get('genre', '')}；"
        f"背景：{script.get('setting', '')}；主线：{script.get('premise', '')}\n"
        f"当前第 {current} 幕（预计 {acts} 幕左右，不是硬限制）。"
        f"关键分支：{branches}。结局候选：{endings}。\n"
        + final_hint
        + " 关键选择用 <opt branch=\"id\" impact=\"major\"> 标记。"
    )
