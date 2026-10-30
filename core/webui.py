# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugin WebUI API for character sprites, backgrounds and layout tuning."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .assets import AssetStore, EMOTIONS, normalize_layout
from .config import PluginConfig
from .renderer import Renderer
from .render_utils import render_image
from .state import Session

try:
    from astrbot.api.web import error_response, json_response, request

    WEB_API_AVAILABLE = True
except Exception:  # pragma: no cover - older AstrBot without plugin pages
    error_response = json_response = request = None  # type: ignore
    WEB_API_AVAILABLE = False

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("astrbot.plugin.gal_choice.webui")

PLUGIN_NAME = "astrbot_plugin_gal_choice"


class GalWebUI:
    def __init__(
        self,
        plugin,
        assets: AssetStore,
        renderer: Renderer,
        config: PluginConfig,
    ):
        self.plugin = plugin
        self.assets = assets
        self.renderer = renderer
        self.config = config

    def register(self) -> None:
        if not WEB_API_AVAILABLE:
            logger.info("[gal] 当前 AstrBot 不支持插件可视化视图，跳过 WebUI 注册")
            return
        context = getattr(self.plugin, "context", None)
        register = getattr(context, "register_web_api", None)
        if not callable(register):
            logger.info("[gal] 当前 AstrBot 没有 register_web_api，跳过 WebUI 注册")
            return
        base = f"/{PLUGIN_NAME}"
        routes = [
            ("/state", self.get_state, ["GET"], "GalGame 资产状态"),
            ("/character/create", self.create_character, ["POST"], "新建角色"),
            ("/character/save", self.save_character, ["POST"], "保存角色布局/名称"),
            ("/character/activate", self.activate_character, ["POST"], "切换角色"),
            ("/character/delete", self.delete_character, ["POST"], "删除角色"),
            ("/upload", self.upload_asset, ["POST"], "上传立绘/背景（兼容旧接口）"),
            (
                "/upload/background",
                self.upload_background,
                ["POST"],
                "上传背景",
            ),
            (
                "/upload/sprite/<character_id>/<emotion>",
                self.upload_sprite,
                ["POST"],
                "上传角色立绘",
            ),
            ("/sprite/bind", self.bind_sprite, ["POST"], "多个情绪共用一张立绘"),
            ("/background/select", self.select_background, ["POST"], "选择背景"),
            ("/settings/save", self.save_settings, ["POST"], "保存外观设置"),
            ("/preview", self.preview, ["POST"], "渲染预览图"),
        ]
        for suffix, handler, methods, desc in routes:
            register(f"{base}{suffix}", handler, methods, desc)

    # ---------- helpers ----------

    def _state(self) -> dict:
        return self.assets.state()

    @staticmethod
    def _payload(payload) -> dict:
        return payload if isinstance(payload, dict) else {}

    # ---------- endpoints ----------

    async def get_state(self):
        return json_response(self._state())

    async def create_character(self):
        payload = self._payload(await request.json(default={}))
        name = str(payload.get("name") or "").strip()
        try:
            profile = self.assets.create(name)
        except Exception as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"ok": True, "profile": profile.id, **self._state()})

    async def save_character(self):
        payload = self._payload(await request.json(default={}))
        profile_id = str(payload.get("id") or "").strip()
        if not profile_id:
            return error_response("缺少角色 id", status_code=400)
        layout = payload.get("layout")
        name = payload.get("name")
        try:
            if layout is not None:
                self.assets.save_layout(
                    profile_id,
                    normalize_layout(layout if isinstance(layout, dict) else {}),
                )
            if name is not None and profile_id != "builtin":
                self.assets.update(profile_id, name=str(name))
        except Exception as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"ok": True, **self._state()})

    async def activate_character(self):
        payload = self._payload(await request.json(default={}))
        profile_id = str(payload.get("id") or "").strip()
        try:
            self.assets.activate(profile_id)
        except Exception as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"ok": True, **self._state()})

    async def delete_character(self):
        payload = self._payload(await request.json(default={}))
        profile_id = str(payload.get("id") or "").strip()
        try:
            self.assets.delete(profile_id)
        except Exception as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"ok": True, **self._state()})

    async def upload_background(self):
        files = await request.files()
        upload = files.get("file")
        if upload is None:
            return error_response("缺少上传文件", status_code=400)
        try:
            name = await self.assets.save_background(upload)
            return json_response({"ok": True, "background": name, **self._state()})
        except Exception as exc:
            return error_response(str(exc), status_code=400)

    async def upload_sprite(self, character_id: str, emotion: str):
        files = await request.files()
        upload = files.get("file")
        if upload is None:
            return error_response("缺少上传文件", status_code=400)
        try:
            profile = await self.assets.save_sprite(
                str(character_id or "").strip(),
                str(emotion or "default").strip(),
                upload,
            )
            return json_response(
                {
                    "ok": True,
                    "profile": profile.id,
                    "emotion": emotion,
                    **self._state(),
                }
            )
        except Exception as exc:
            return error_response(str(exc), status_code=400)

    async def upload_asset(self):
        files = await request.files()
        upload = files.get("file")
        if upload is None:
            return error_response("缺少上传文件", status_code=400)
        kind = str(request.query.get("kind") or "sprite").lower()
        try:
            if kind == "background":
                name = await self.assets.save_background(upload)
                return json_response({"ok": True, "background": name, **self._state()})
            profile_id = str(request.query.get("character_id") or "").strip()
            emotion = str(request.query.get("emotion") or "default").strip()
            profile = await self.assets.save_sprite(profile_id, emotion, upload)
            return json_response(
                {
                    "ok": True,
                    "profile": profile.id,
                    "emotion": emotion,
                    **self._state(),
                }
            )
        except Exception as exc:
            return error_response(str(exc), status_code=400)

    async def bind_sprite(self):
        payload = self._payload(await request.json(default={}))
        profile_id = str(payload.get("id") or "").strip()
        emotion = str(payload.get("emotion") or "").strip()
        filename = str(payload.get("file") or "").strip()
        if not filename:
            return error_response("缺少立绘文件", status_code=400)
        try:
            self.assets.bind_sprite(profile_id, emotion, filename)
        except Exception as exc:
            return error_response(str(exc), status_code=400)
        return json_response({"ok": True, **self._state()})

    async def select_background(self):
        payload = self._payload(await request.json(default={}))
        name = str(payload.get("name") or "").strip()
        if name and self.assets.resolve_background(name) is None:
            return error_response("背景文件不存在", status_code=400)
        self.config.set("background_file", name)
        return json_response({"ok": True, **self._state()})

    async def save_settings(self):
        payload = self._payload(await request.json(default={}))
        if "bot_label" in payload:
            self.config.set("bot_label", str(payload.get("bot_label") or "小鲸鱼")[:30])
        if "free_option_hint" in payload:
            self.config.set(
                "free_option_hint",
                str(payload.get("free_option_hint") or "✎ 自己说点什么…")[:40],
            )
        if "box_alpha" in payload:
            try:
                alpha = max(0.2, min(1.0, float(payload.get("box_alpha"))))
            except (TypeError, ValueError):
                alpha = self.config.float("box_alpha", 0.94, 0.2, 1.0)
            self.config.set("box_alpha", alpha)
        if "image_quality" in payload:
            try:
                quality = max(30, min(100, int(payload.get("image_quality"))))
            except (TypeError, ValueError):
                quality = self.config.int("image_quality", 90, 30, 100)
            self.config.set("image_quality", quality)
        if "render_endpoint" in payload:
            endpoint = str(payload.get("render_endpoint") or "").strip()
            for item in endpoint.replace(";", ",").split(","):
                item = item.strip()
                if item and not item.startswith(("http://", "https://")):
                    return error_response("文转图端点必须是 http(s) 地址", status_code=400)
            self.config.set("render_endpoint", endpoint)
        if "render_backend" in payload:
            backend = str(payload.get("render_backend") or "auto").strip().lower()
            if backend == "local":
                backend = "auto"
            if backend not in {"auto", "browser", "pillow", "remote"}:
                backend = "auto"
            self.config.set("render_backend", backend)
        if "dialogue_max_lines" in payload:
            try:
                lines = max(1, min(3, int(payload.get("dialogue_max_lines"))))
            except (TypeError, ValueError):
                lines = self.config.int("dialogue_max_lines", 3, 1, 3)
            self.config.set("dialogue_max_lines", lines)
        if "voice_line_gap_ms" in payload:
            try:
                gap = max(0, min(2500, int(payload.get("voice_line_gap_ms"))))
            except (TypeError, ValueError):
                gap = self.config.int("voice_line_gap_ms", 1000, 0, 2500)
            self.config.set("voice_line_gap_ms", gap)
        if "gal_debounce_enabled" in payload:
            self.config.set("gal_debounce_enabled", bool(payload.get("gal_debounce_enabled")))
        if "gal_debounce_seconds" in payload:
            try:
                seconds = max(0.2, min(5.0, float(payload.get("gal_debounce_seconds"))))
            except (TypeError, ValueError):
                seconds = self.config.float("gal_debounce_seconds", 1.0, 0.2, 5.0)
            self.config.set("gal_debounce_seconds", seconds)
        if "gal_debounce_max_seconds" in payload:
            try:
                seconds = max(1.0, min(15.0, float(payload.get("gal_debounce_max_seconds"))))
            except (TypeError, ValueError):
                seconds = self.config.float("gal_debounce_max_seconds", 5.0, 1.0, 15.0)
            self.config.set("gal_debounce_max_seconds", seconds)
        if "background_mode" in payload:
            mode = str(payload.get("background_mode") or "session")
            if mode not in {"session", "random", "fixed"}:
                mode = "session"
            self.config.set("background_mode", mode)
        return json_response({"ok": True, **self._state()})

    async def preview(self):
        payload = self._payload(await request.json(default={}))
        quote = str(payload.get("quote") or "最近总是睡不好，有没有什么办法能改善一下？")[:120]
        say = str(payload.get("say") or self.config.str("default_say", "这几个方向，你想先聊哪个？"))
        emotion = str(payload.get("emotion") or "笑")
        raw_options = payload.get("options")
        if isinstance(raw_options, list) and raw_options:
            options = [str(item) for item in raw_options if str(item).strip()][:4]
        else:
            options = ["先从作息调整开始", "试试睡前放松练习", "聊聊压力和心事", "要不要看医生"]
        if len(options) < 2:
            options = ["先说说是怎么回事", "直接给我建议"]
        session = Session(key="webui_preview", turn_id=1)
        layout_override = payload.get("layout")
        if not isinstance(layout_override, dict):
            layout_override = None
        try:
            template, data = self.renderer.build(
                session=session,
                quote=quote,
                options=options,
                say=say,
                emotion=emotion,
                speaker="玩家",
                user_id="",
                layout=layout_override,
            )
            image = await render_image(
                self.plugin,
                self.config,
                template,
                data,
                options={
                    "type": "jpeg",
                    "quality": self.config.int("image_quality", 90, 30, 100),
                    "timeout": 20000,
                    "scale": "css",
                    "animations": "disabled",
                },
                timeout=90,
            )
        except asyncio.TimeoutError:
            logger.warning("[gal] WebUI 预览超时：文转图服务 90 秒内没有返回")
            return error_response("预览超时，请稍后重试", status_code=504)
        except Exception as exc:
            logger.warning("[gal] WebUI 预览失败: %r", exc)
            return error_response(f"预览失败: {exc or exc.__class__.__name__}", status_code=500)
        return json_response(
            {
                "url": image,
                "layout": normalize_layout(
                    layout_override if layout_override is not None else self.assets.active().layout
                ),
            }
        )
