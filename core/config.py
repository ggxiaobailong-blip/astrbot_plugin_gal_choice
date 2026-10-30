# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed access to the plugin config with sane defaults.

The values here are the single source of truth for defaults.  The JSON schema in
``_conf_schema.json`` mirrors them for the WebUI, but the plugin never depends on
the schema being present.
"""

from __future__ import annotations

import re
from pathlib import Path

from .emotions import EMOTION_IDS

PLUGIN_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = PLUGIN_DIR / "assets"
BACKGROUND_DIR = PLUGIN_DIR / "background"
TEMPLATE_DIR = PLUGIN_DIR / "templates"

DEFAULT_EMOTION_MAP = {
    "happy": "whale_girl_moe.webp",
    "angry": "emotions/angry.webp",
    "surprised": "emotions/surprised.webp",
    "calm": "whale_girl_moe.webp",
    "sad": "emotions/teary.webp",
    "shy": "emotions/blank.webp",
    "tired": "emotions/frown.webp",
    "worried": "emotions/blank.webp",
    "moved": "emotions/blank.webp",
    "confused": "emotions/frown.webp",
    "indifferent": "emotions/frown.webp",
    "scared": "emotions/endure.webp",
}

DEFAULTS: dict = {
    "mode_on_words": "进入gal模式,gal模式,切换gal模式,开始gal",
    "mode_off_words": "退出gal模式,退出gal,结束gal,退出游戏,关闭gal",
    "mode_idle_minutes": 120,
    "option_ttl": 600,
    "bot_label": "小鲸鱼",
    "default_say": "这几个方向，你想先聊哪个？",
    "say_max_units": 46.0,
    "option_max_units": 16.0,
    "free_option_hint": "✎ 自己说点什么…",
    "free_input_enabled": True,
    "emotion_default_file": "whale_girl_moe.webp",
    "emotion_map": dict(DEFAULT_EMOTION_MAP),
    "background_file": "",
    "background_mode": "session",
    "background_blur": 20,
    "box_alpha": 0.94,
    "show_icons": True,
    "show_turn_label": True,
    "say_font_size": 26,
    "image_quality": 90,
    "render_endpoint": "",
    "voice_enabled": True,
    "voice_probability": 1.0,
    "tts_provider_id": "",
    "tts_emotion_mode": "auto",
    "gal_provider_id": "",
    "avatar_enabled": True,
    "avatar_size": 100,
}


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return default


def safe_asset(base: Path, relative: str) -> Path | None:
    """Resolve *relative* below *base*, rejecting absolute paths and ``..``."""
    if not relative:
        return None
    try:
        rel = Path(str(relative).strip())
    except (TypeError, ValueError):
        return None
    if rel.is_absolute() or ".." in rel.parts:
        return None
    try:
        base_resolved = base.resolve()
        target = (base_resolved / rel).resolve()
    except OSError:
        return None
    if not target.is_relative_to(base_resolved):
        return None
    return target if target.is_file() else None


def plugin_data_dir(plugin_name: str = "astrbot_plugin_gal_choice") -> Path:
    """Return ``data/plugin_data/<plugin_name>`` with a test-friendly fallback."""
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        base = Path(get_astrbot_data_path())
    except Exception:
        base = Path.cwd() / "data"
    path = base / "plugin_data" / plugin_name
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


class PluginConfig:
    """Small wrapper around the raw config dict."""

    def __init__(self, raw: dict | None):
        self.raw = raw if isinstance(raw, dict) else {}

    def get(self, key: str, default=None):
        if key in self.raw:
            value = self.raw[key]
        else:
            value = DEFAULTS.get(key, default)
        if value is None:
            return default
        if isinstance(value, str) and not value.strip() and default not in (None, ""):
            return default
        return value

    def str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        return str(value).strip() if value is not None else default

    def int(self, key: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
        try:
            value = int(float(self.get(key, default)))
        except (TypeError, ValueError):
            value = default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def float(self, key: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
        try:
            value = float(self.get(key, default))
        except (TypeError, ValueError):
            value = default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def bool(self, key: str, default: bool = False) -> bool:
        return _as_bool(self.get(key, default), default)

    def words(self, key: str, default: str = "") -> list[str]:
        raw = self.str(key, default)
        parts = [part.strip() for part in re.split(r"[,，、;\n]+", raw) if part.strip()]
        seen: set[str] = set()
        result: list[str] = []
        for part in parts:
            folded = part.casefold()
            if folded not in seen:
                seen.add(folded)
                result.append(part)
        return result

    def emotion_map(self) -> dict[str, str]:
        raw = self.get("emotion_map", DEFAULT_EMOTION_MAP)
        out = dict(DEFAULT_EMOTION_MAP)
        if isinstance(raw, dict):
            # Built-in sprites are keyed by visual group.  Legacy Chinese keys
            # ("笑"/"忍耐"...) are ignored so the new built-in mapping takes
            # effect for existing configs; custom characters use characters.json.
            for key, value in raw.items():
                if (
                    isinstance(key, str)
                    and key in EMOTION_IDS
                    and isinstance(value, str)
                    and value.strip()
                ):
                    out[key] = value.strip()
        return out

    def asset(self, relative: str) -> Path | None:
        return safe_asset(ASSETS_DIR, relative)

    def background(self, name: str) -> Path | None:
        return safe_asset(BACKGROUND_DIR, name)

    def set(self, key: str, value) -> None:
        """Update a config value and persist it when AstrBotConfig is available."""
        self.raw[key] = value
        save = getattr(self.raw, "save_config", None)
        if callable(save):
            try:
                save()
            except Exception:
                pass
