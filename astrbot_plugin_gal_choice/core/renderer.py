# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the GalGame HTML and resolve its local assets."""

from __future__ import annotations

import base64
import io
import random
from pathlib import Path

from .assets import AssetStore, normalize_layout
from .config import TEMPLATE_DIR, PluginConfig
from .parser import LETTERS, display_units, fit_text

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover - local unit tests without AstrBot
    import logging

    logger = logging.getLogger("astrbot.plugin.gal_choice.renderer")

W, H = 1280, 720
BOX_TOP = int(H * 0.69)
OPT_W, OPT_H, OPT_GAP = 380, 50, 9
OPT_LEFT = int(W * 0.625)
_MIME = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


class Renderer:
    def __init__(self, config: PluginConfig, assets: AssetStore):
        self.config = config
        self.assets = assets
        self._template = (TEMPLATE_DIR / "gal.html").read_text(encoding="utf-8")
        self._data_url_cache: dict[tuple[str, int, int], str] = {}
        self._warned: set[str] = set()

    @property
    def template(self) -> str:
        return self._template

    def _warn_once(self, message: str, key: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message)

    # ---------- assets ----------

    def backgrounds(self) -> list[str]:
        return self.assets.background_names()

    def pick_background(self, session_bg: str = "") -> str:
        fixed = self.config.str("background_file")
        mode = self.config.str("background_mode", "session")
        if fixed and self.assets.resolve_background(fixed):
            return fixed
        if mode != "random" and session_bg and self.assets.resolve_background(session_bg):
            return session_bg
        candidates = self.backgrounds()
        return random.choice(candidates) if candidates else ""

    def resolve_character(self, emotion: str) -> Path | None:
        profile = self.assets.active()
        path = self.assets.resolve_sprite(profile, emotion)
        if path is None:
            self._warn_once("[gal] 找不到任何立绘，图片将不带角色", "char:none")
        return path

    def data_url(
        self,
        path: Path | None,
        max_size: tuple[int, int] = (1000, 1500),
        quality: int = 78,
        force_jpeg: bool = False,
    ) -> str:
        if path is None:
            return ""
        try:
            stat = path.stat()
        except OSError:
            return ""
        key = (str(path), stat.st_mtime_ns, stat.st_size, max_size, quality, force_jpeg)
        cached = self._data_url_cache.get(key)
        if cached is not None:
            return cached
        if stat.st_size > 12 * 1024 * 1024:
            self._warn_once(f"[gal] 资源过大，跳过 base64: {path}", f"big:{path}")
            return ""
        mime = _MIME.get(path.suffix.lower(), "image/jpeg")
        raw_bytes: bytes
        try:
            # Remote T2I services choke on ~800KB base64 payloads.  Re-encode
            # large sprites/backgrounds to a compact image before embedding.
            from PIL import Image

            image = Image.open(path)
            try:
                needs_optimize = path.suffix.lower() != ".gif" and (
                    stat.st_size > 120 * 1024
                    or image.width > max_size[0]
                    or image.height > max_size[1]
                )
                if needs_optimize:
                    image.thumbnail(max_size)
                    buffer = io.BytesIO()
                    if force_jpeg or image.mode in ("RGB", "L"):
                        image.convert("RGB").save(
                            buffer, "JPEG", quality=quality, optimize=True
                        )
                        mime = "image/jpeg"
                    else:
                        if image.mode not in ("RGB", "RGBA"):
                            image = image.convert("RGBA")
                        image.save(buffer, "WEBP", quality=quality, method=4)
                        mime = "image/webp"
                    optimized = buffer.getvalue()
                    if optimized and len(optimized) < stat.st_size:
                        raw_bytes = optimized
                    else:
                        raw_bytes = path.read_bytes()
                else:
                    raw_bytes = path.read_bytes()
            finally:
                image.close()
        except Exception:
            try:
                raw_bytes = path.read_bytes()
                mime = _MIME.get(path.suffix.lower(), "image/jpeg")
            except OSError as exc:
                logger.warning("[gal] 读取资源失败 %s: %s", path, exc)
                return ""
        try:
            raw = base64.b64encode(raw_bytes).decode("ascii")
        except Exception:
            return ""
        url = f"data:{mime};base64,{raw}"
        self._data_url_cache[key] = url
        return url

    def avatar_url(self, user_id: str) -> str:
        if not self.config.bool("avatar_enabled", True):
            return ""
        user_id = (user_id or "").strip()
        if not user_id.isdigit():
            return ""
        size = self.config.int("avatar_size", 100, 40, 640)
        return f"https://q1.qlogo.cn/g?b=sdk&nk={user_id}&s={size}"

    # ---------- page ----------

    def build(
        self,
        *,
        session,
        quote: str,
        options: list[str],
        say: str,
        emotion: str,
        speaker: str,
        user_id: str,
    ) -> tuple[str, dict]:
        profile = self.assets.active()
        layout = normalize_layout(profile.layout)
        bg_name = self.pick_background(session.bg)
        if bg_name:
            session.bg = bg_name
        bg_url = (
            self.data_url(
                self.assets.resolve_background(bg_name),
                max_size=(960, 540),
                quality=58,
                force_jpeg=True,
            )
            if bg_name
            else ""
        )
        char_url = self.data_url(
            self.assets.resolve_sprite(profile, emotion),
            max_size=(820, 1230),
            quality=68,
        )

        default_say = self.config.str("default_say", "这几个方向，你想先聊哪个？")
        say_text = fit_text(
            (say or "").strip() or default_say,
            self.config.float("say_max_units", 46.0, 8, 80),
        )
        units = display_units(say_text)
        base_font = self.config.int("say_font_size", 26, 18, 34)
        say_font = base_font
        if units > 42:
            say_font = max(20, base_font - 2)
        if units > 56:
            say_font = max(18, base_font - 4)

        option_max = min(20.0, self.config.float("option_max_units", 16.0, 4, 30))
        items: list[dict] = []
        for index, option in enumerate(options[:4]):
            items.append(
                {
                    "letter": LETTERS[index],
                    "text": fit_text(option, option_max),
                    "cls": "",
                    "letter_cls": "",
                }
            )
        if self.config.bool("free_input_enabled", True):
            free_hint = self.config.str("free_option_hint", "✎ 自己说点什么…")
            items.append(
                {
                    "letter": "0",
                    "text": fit_text(free_hint, min(24.0, max(8.0, option_max + 6))),
                    "cls": "is-free",
                    "letter_cls": "free-letter",
                }
            )

        count = max(1, len(items))
        bottom = BOX_TOP - 14
        top_start = bottom - count * OPT_H - max(0, count - 1) * OPT_GAP
        for index, item in enumerate(items):
            item["top"] = top_start + index * (OPT_H + OPT_GAP)

        turn_id = max(0, int(session.turn_id))
        turn_label = ""
        if self.config.bool("show_turn_label", True):
            turn_label = f"第 {turn_id} 幕" if turn_id else "序章"

        avatar = self.avatar_url(user_id)
        data = {
            "W": W,
            "H": H,
            "bg_url": bg_url,
            "char_url": char_url,
            "char_profile": profile.id,
            "char_left": layout["left"],
            "char_top": layout["top"],
            "char_height": layout["height"],
            "char_max_width": layout["max_width"],
            "quote": fit_text(quote or "（无原文）", 90),
            "speaker": fit_text(speaker or "某人", 18),
            "avatar": avatar,
            "avatar_letter": (speaker or "?")[:1],
            "bot_label": fit_text(self.config.str("bot_label", "小鲸鱼"), 14),
            "say": say_text,
            "say_font": say_font,
            "options": items,
            "opt_header_top": max(0, top_start - 28),
            "show_icons": self.config.bool("show_icons", True),
            "turn_label": turn_label,
            "hint": "回复字母选择 · 或直接输入你想说的",
            "box_alpha": self.config.float("box_alpha", 0.94, 0.2, 1.0),
            "bg_blur": self.config.int("background_blur", 20, 0, 60),
            "has_avatar": bool(avatar),
        }
        return self._template, data
