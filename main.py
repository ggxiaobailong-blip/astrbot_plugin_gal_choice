# SPDX-License-Identifier: AGPL-3.0-or-later
"""GalGame 选项出图插件。

用户通过 /gal start 或“进入gal模式”进入 gal 模式后，模型每轮只输出
「表情 + 台词 + 2~4 个选项」，插件把它渲染成一张 GalGame 界面图；
用户回字母、数字、选项原文或自由输入继续，台词同时可配 TTS 语音。
"""

from __future__ import annotations

import asyncio
import re
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star

if __package__:
    from .core.assets import AssetStore
    from .core.config import PluginConfig, plugin_data_dir
    from .core.affection import clamp, mood_for, stage_for, tone_hint
    from .core.parser import (
        LETTERS,
        GalLine,
        OptionMatch,
        clean_message,
        is_exit_intent,
        is_start_intent,
        match_option,
        parse_gal_reply,
        phrase_hit,
        readable_fallback,
    )
    from .core.prompts import (
        AMBIGUOUS_HINT,
        ENTRY_HINT,
        EXIT_HINT,
        FREE_HINT,
        FREE_SLOT_HINT,
        GAL_RULES,
        MEDIA_HINT,
        NO_OPTIONS_HINT,
        PICK_HINT,
    )
    from .core.renderer import Renderer
    from .core.render_utils import render_image
    from .core.saves import SaveStore
    from .core.script import brief as script_brief, ending_by_id, fallback_outline, outline_prompt, parse_outline
    from .core.state import Session, SessionStore
    from .core.voice import VoiceService
    from .core.webui import GalWebUI
else:  # pragma: no cover - only used when running the file directly
    from core.assets import AssetStore
    from core.affection import clamp, mood_for, stage_for, tone_hint
    from core.config import PluginConfig, plugin_data_dir
    from core.parser import (
        LETTERS,
        GalLine,
        OptionMatch,
        clean_message,
        is_exit_intent,
        is_start_intent,
        match_option,
        parse_gal_reply,
        phrase_hit,
        readable_fallback,
    )
    from core.prompts import (
        AMBIGUOUS_HINT,
        ENTRY_HINT,
        EXIT_HINT,
        FREE_HINT,
        FREE_SLOT_HINT,
        GAL_RULES,
        MEDIA_HINT,
        NO_OPTIONS_HINT,
        PICK_HINT,
    )
    from core.renderer import Renderer
    from core.render_utils import render_image
    from core.saves import SaveStore
    from core.script import brief as script_brief, ending_by_id, fallback_outline, outline_prompt, parse_outline
    from core.state import Session, SessionStore
    from core.voice import VoiceService
    from core.webui import GalWebUI

PLUGIN_NAME = "astrbot_plugin_gal_choice"
_GENERIC_START = ("开始", "来吧", "随便", "你决定", "都行", "继续")


def _on_waiting_llm_request():
    """Use the waiting hook when available; older/local stubs may lack it."""
    decorator = getattr(filter, "on_waiting_llm_request", None)
    if callable(decorator):
        return decorator()
    return lambda fn: fn


class GalChoicePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = PluginConfig(config)
        data_dir = plugin_data_dir(PLUGIN_NAME)
        self.store = SessionStore(
            data_dir / "sessions.json",
            idle_seconds=self.config.int("mode_idle_minutes", 120, 5, 7 * 24 * 60) * 60,
            option_ttl=self.config.int("option_ttl", 600, 30, 86400),
        )
        self.saves = SaveStore(10)
        self.assets = AssetStore(self.config)
        self.renderer = Renderer(self.config, self.assets)
        self.voice = VoiceService(context, self.config)
        self.webui = GalWebUI(self, self.assets, self.renderer, self.config)
        self.webui.register()
        self._pending_voice: dict[str, tuple[list, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._provider_warned: set[str] = set()
        self._debounce_windows: dict[str, dict] = {}
        self._warn_external_debounce()

    # ---------- 基础 ----------

    def _key(self, event: AstrMessageEvent) -> str:
        try:
            umo = event.unified_msg_origin
        except Exception:
            umo = ""
        try:
            uid = event.get_sender_id()
        except Exception:
            uid = ""
        return f"{umo}|{uid}" if umo else str(uid or "unknown")

    @staticmethod
    def _is_private(event: AstrMessageEvent) -> bool:
        checker = getattr(event, "is_private_chat", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:
            return True

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _entry_words(self) -> list[str]:
        return self.config.words(
            "mode_on_words",
            "gal,进入gal模式,gal模式,切换gal模式,开始gal,gal启动,启动gal,开始gal模式,开启gal,开gal",
        )

    def _trigger_text(self, event: AstrMessageEvent) -> str:
        """Normalize a group message: drop leading @mentions and punctuation."""
        text = clean_message(event.message_str).strip()
        text = re.sub(r"^(?:\s*@[^\s@]+)+", "", text).strip()
        return text.strip(" \t\r\n。.!！?？~～,，")

    def _exit_words(self) -> list[str]:
        return self.config.words("mode_off_words", "退出gal模式,退出gal,结束gal,退出游戏,关闭gal")

    def _bot_label(self) -> str:
        return self.config.str("bot_label", "小鲸鱼")

    def _default_say(self) -> str:
        return self.config.str("default_say", "这几个方向，你想先聊哪个？")

    def _fallback_text(self, say: str, options: list[str]) -> str:
        return readable_fallback(
            say,
            options,
            self._bot_label(),
            self._default_say(),
        )

    # ---------- 模型切换 ----------

    async def _current_provider_id(self, umo: str) -> str:
        try:
            return await self.context.get_current_chat_provider_id(umo)
        except Exception:
            return ""

    async def _switch_provider(self, event: AstrMessageEvent, session: Session, provider_id: str) -> bool:
        provider_id = (provider_id or "").strip()
        if not provider_id:
            return True
        umo = event.unified_msg_origin
        current = await self._current_provider_id(umo)
        if current == provider_id:
            return True
        try:
            from astrbot.core.provider.entities import ProviderType

            await self.context.provider_manager.set_provider(
                provider_id,
                ProviderType.CHAT_COMPLETION,
                umo,
            )
        except Exception as exc:
            if provider_id not in self._provider_warned:
                self._provider_warned.add(provider_id)
                logger.warning("[gal] 切换到模型 %s 失败: %s", provider_id, exc)
            return False
        if not session.prev_provider_id and current:
            session.prev_provider_id = current
        session.provider_id = provider_id
        logger.info("[gal] 本会话切换到模型 %s", provider_id)
        return True

    async def _restore_provider(self, event: AstrMessageEvent, session: Session) -> None:
        previous = (session.prev_provider_id or "").strip()
        if not previous:
            return
        try:
            from astrbot.core.provider.entities import ProviderType

            await self.context.provider_manager.set_provider(
                previous,
                ProviderType.CHAT_COMPLETION,
                event.unified_msg_origin,
            )
            session.prev_provider_id = ""
            logger.info("[gal] 已恢复模型 %s", previous)
        except Exception as exc:
            logger.warning("[gal] 恢复模型 %s 失败: %s", previous, exc)

    # ---------- 模式 ----------

    async def _generate_outline(self, event: AstrMessageEvent, session: Session, setting: str = "") -> None:
        setting = (setting or "").strip()
        try:
            provider = self.context.get_using_provider(event.unified_msg_origin)
        except Exception:
            provider = None
        if provider is None or not hasattr(provider, "text_chat"):
            session.script = fallback_outline(setting)
            return
        try:
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=outline_prompt(setting),
                    system_prompt="你是 GalGame 编剧。只输出合法 JSON，不要 Markdown。",
                ),
                timeout=45,
            )
            text = getattr(response, "completion_text", "") or ""
            session.script = parse_outline(text, setting)
            logger.info(
                "[gal] 生成剧本大纲 title=%s acts=%s",
                session.script.get("title"),
                session.script.get("acts"),
            )
        except Exception as exc:
            logger.warning("[gal] 生成剧本大纲失败，使用默认大纲: %s", exc)
            session.script = fallback_outline(setting)

    def _entry_setting(self, text: str) -> str:
        raw = (text or "").strip()
        candidates = sorted(self._entry_words(), key=len, reverse=True)
        for word in candidates:
            if word and raw.casefold().startswith(word.casefold()):
                return raw[len(word):].strip(" \t\r\n，,。.!！：:；;")
        return ""

    async def _enter(self, event: AstrMessageEvent, session: Session, setting: str = "") -> None:
        session.mode = "gal"
        session.just_entered = True
        session.options = []
        session.option_meta = []
        session.quote = ""
        session.emotion = ""
        session.turn_id = 0
        session.history = []
        session.bg = ""
        session.options_at = 0.0
        session.affection = 50
        session.mood = "calm"
        session.affection_delta = 0
        session.script = {}
        session.ending_id = ""
        session.ending_title = ""
        session.ended = False
        session.touch()
        target = session.provider_id or self.config.str("gal_provider_id")
        if target:
            await self._switch_provider(event, session, target)
        await self._generate_outline(event, session, setting)

    async def _exit(self, event: AstrMessageEvent, session: Session) -> None:
        await self._restore_provider(event, session)
        session.mode = "chat"
        session.options = []
        session.option_meta = []
        session.quote = ""
        session.emotion = ""
        session.turn_id = 0
        session.just_entered = False
        session.history = []
        session.bg = ""
        session.options_at = 0.0
        session.script = {}
        session.ending_id = ""
        session.ending_title = ""
        session.ended = False
        session.touch()

    # ---------- 指令 ----------

    @filter.command("gal")
    async def gal(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """GalGame 模式控制：/gal [start|stop|status|model|voice|reset|help]。"""
        key = self._key(event)
        if not self._is_private(event):
            yield event.plain_result("GalGame 模式只在私聊开放。")
            return
        session = self.store.get_or_create(key)
        action = (action or "").strip().lower()
        value = (value or "").strip()

        if action in {"new", "新周目", "重开"}:
            await self._enter(event, session, value)
            event.set_extra("gal_quote", "新周目")
            await self.store.save()
            return

        if not action or action in {"start", "begin", "开始", "进入"}:
            if session.mode == "gal":
                # gal_gate 可能已经在本条消息里进入模式；这时不重复提示，
                # 也不产出结果，让后面的 LLM 直接生成开场图。
                if session.just_entered:
                    event.set_extra("gal_quote", "开始")
                    return
                yield event.plain_result("已经在 GalGame 模式里了。选一个选项，或发送 /gal reset 重开。")
                return
            await self._enter(event, session, value)
            event.set_extra("gal_quote", "开始")
            await self.store.save()
            # 不 yield：让默认 LLM 链路接手，由 inject_choice 生成开场白和选项。
            return

        if action in {"stop", "exit", "end", "quit", "退出", "结束"}:
            if session.mode != "gal":
                yield event.plain_result("当前不在 GalGame 模式。发送 /gal start 进入。")
                return
            await self._exit(event, session)
            await self.store.save()
            yield event.plain_result("已退出 GalGame 模式，接下来正常聊天。")
            return

        if action in {"status", "状态"}:
            if session.mode not in {"gal", "ended"}:
                yield event.plain_result("当前是普通聊天模式。发送 /gal start 进入 GalGame 模式。")
                return
            lines = [
                f"模式：{'GalGame · 已完结' if session.ended else 'GalGame'}",
                f"进度：{('第 ' + str(session.turn_id) + ' 幕') if session.turn_id else '序章'}",
                f"好感：{session.affection} · {stage_for(session.affection)['label']}",
            ]
            if session.script:
                lines.append(f"剧本：{session.script.get('title', '')}（预计 {session.script.get('acts', 6)} 幕）")
            if session.ending_title:
                lines.append(f"结局：{session.ending_title}")
            if session.options:
                lines.append("当前选项：")
                for index, option in enumerate(session.options):
                    letter = LETTERS[index] if index < len(LETTERS) else str(index + 1)
                    lines.append(f"  {letter}. {option}")
                lines.append("  0. 自己说点什么")
            if session.history:
                lines.append("最近选择：" + "；".join(session.history[-3:]))
            model = session.provider_id or self.config.str("gal_provider_id")
            lines.append(f"模型：{model or '跟随当前会话'}")
            voice_on = (
                session.voice_enabled
                if isinstance(session.voice_enabled, bool)
                else self.config.bool("voice_enabled", True)
            )
            lines.append(f"语音：{'开' if voice_on else '关'}")
            yield event.plain_result("\n".join(lines))
            return

        if action in {"save", "存档"}:
            if session.mode != "gal":
                yield event.plain_result("当前不在 GalGame 模式，无法存档。")
                return
            name = value or f"存档 {len(self.saves.list(key)) + 1}"
            saved = await self.saves.save(key, name, session)
            yield event.plain_result(
                f"已存档「{saved}」：第 {session.turn_id or 0} 幕，好感 {session.affection}。"
            )
            return

        if action in {"load", "读档"}:
            slots = self.saves.list(key)
            if not slots:
                yield event.plain_result("还没有存档。用 /gal save 名字 保存当前进度。")
                return
            if not value:
                yield event.plain_result(
                    "当前存档：\n"
                    + "\n".join(
                        f"  {item['name']}（第 {item['turn']} 幕，好感 {item['affection']}）"
                        for item in slots
                    )
                    + "\n用 /gal load 存档名 读取。"
                )
                return
            payload = await self.saves.load(key, value)
            if payload is None:
                yield event.plain_result(f"找不到存档「{value}」。用 /gal load 查看列表。")
                return
            loaded = Session.from_dict(key, payload)
            self.store.put(loaded)
            if loaded.mode == "gal":
                target = loaded.provider_id or self.config.str("gal_provider_id")
                if target:
                    await self._switch_provider(event, loaded, target)
            await self.store.save()
            yield event.plain_result(
                f"已读取「{value}」：第 {loaded.turn_id or 0} 幕，好感 {loaded.affection}。"
            )
            return

        if action in {"saves", "存档列表"}:
            slots = self.saves.list(key)
            if not slots:
                yield event.plain_result("还没有存档。用 /gal save 名字 保存当前进度。")
                return
            yield event.plain_result(
                "存档列表：\n"
                + "\n".join(
                    f"  {item['name']}（第 {item['turn']} 幕，好感 {item['affection']}）"
                    for item in slots
                )
            )
            return

        if action in {"delete", "删除存档"}:
            if not value:
                yield event.plain_result("用法：/gal delete 存档名")
                return
            removed = await self.saves.delete(key, value)
            yield event.plain_result(
                f"已删除存档「{value}」。" if removed else f"找不到存档「{value}」。"
            )
            return

        if action in {"model", "模型"}:
            model = value
            if not model or model.lower() in {"status", "show"}:
                current = session.provider_id or self.config.str("gal_provider_id") or "跟随当前会话"
                yield event.plain_result(f"当前 gal 模型：{current}")
                return
            if model.lower() in {"default", "clear", "follow", "跟随", "默认"}:
                session.provider_id = ""
                if session.mode == "gal":
                    await self._restore_provider(event, session)
                session.touch()
                await self.store.save()
                yield event.plain_result("已恢复为跟随当前会话的模型。")
                return
            try:
                provider = self.context.get_provider_by_id(model)
            except Exception:
                provider = None
            if provider is None or not hasattr(provider, "text_chat"):
                yield event.plain_result(f"找不到可用的聊天模型 provider：{model}")
                return
            session.provider_id = model
            if session.mode == "gal":
                ok = await self._switch_provider(event, session, model)
                if not ok:
                    yield event.plain_result(f"切换到模型 {model} 失败，请检查 AstrBot 的提供商配置。")
                    return
            session.touch()
            await self.store.save()
            yield event.plain_result(f"gal 模式将使用模型：{model}")
            return

        if action in {"voice", "语音"}:
            mode = value.lower()
            if mode in {"on", "开", "true", "1"}:
                session.voice_enabled = True
            elif mode in {"off", "关", "false", "0"}:
                session.voice_enabled = False
            else:
                current = (
                    session.voice_enabled
                    if isinstance(session.voice_enabled, bool)
                    else self.config.bool("voice_enabled", True)
                )
                yield event.plain_result(f"本会话语音：{'开' if current else '关'}。用 /gal voice on|off 切换。")
                return
            session.touch()
            await self.store.save()
            yield event.plain_result("本会话语音已" + ("开启。" if session.voice_enabled else "关闭。"))
            return

        if action in {"reset", "重置"}:
            if session.mode == "gal":
                await self._restore_provider(event, session)
            self.store.remove(key)
            await self.store.save()
            yield event.plain_result("本会话的 GalGame 状态已清空。")
            return

        yield event.plain_result(
            "GalGame 模式指令：\n"
            "/gal               进入模式（也可以直接说“gal”）\n"
            "/gal start [题材]   进入模式；可指定“校园恋爱”等题材\n"
            "/gal new [题材]     结束当前局，开启新周目\n"
            "/gal stop          退出模式\n"
            "/gal status        查看当前状态\n"
            "/gal model <id>    指定模型；default 恢复跟随会话\n"
            "/gal voice on|off  开关台词语音\n"
            "/gal save 名字     存档（最多 10 个）\n"
            "/gal load 名字     读档；不带名字查看列表\n"
            "/gal saves         查看存档列表\n"
            "/gal delete 名字   删除存档\n"
            "/gal reset         清空本会话状态\n"
            "/gal help          查看帮助\n\n"
            "进入后回复 A/B/C/D 或 1/2/3/4 选择，回复 0 或直接说话则自由输入。"
        )

    # ---------- 消息闸门 ----------

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1000)
    async def gal_gate(self, event: AstrMessageEvent):
        """在 gal 会话里放行裸字母，并让群聊里的裸字母能够触发 LLM。"""
        try:
            if not self._is_private(event):
                return
            key = self._key(event)
            session = self.store.get(key)
            text = self._trigger_text(event)

            if session is not None and session.mode == "gal":
                # 私聊本来就会唤醒；群聊里必须显式打开这个标志，否则
                # ProcessStage 不会因为一个裸字母去请求 LLM。
                event.is_wake = True
                event.is_at_or_wake_command = True
                # 出图需要完整的最终文本，流式输出会让 on_decorating_result 不可靠
                event.set_extra("enable_streaming", False)
                target = session.provider_id or self.config.str("gal_provider_id")
                if target:
                    await self._switch_provider(event, session, target)
                return

            if text and is_exit_intent(text, self._exit_words()):
                return

            if is_start_intent(text, self._entry_words()):
                session = self.store.get_or_create(key)
                await self._enter(event, session, self._entry_setting(text))
                await self.store.save()
                event.is_wake = True
                event.is_at_or_wake_command = True
                event.set_extra("enable_streaming", False)
                logger.info("[gal] 进入 gal 模式 key=%s", key)
        except Exception as exc:
            logger.error("[gal] 闸门判断失败: %s", exc, exc_info=True)

    def _warn_external_debounce(self) -> None:
        try:
            for star in self.context.get_all_stars():
                if (
                    getattr(star, "name", "") == "astrbot_plugin_reply_merge"
                    and getattr(star, "activated", False)
                ):
                    logger.warning(
                        "[gal] 检测到外部 reply_merge 同时启用；本插件已内置防抖，"
                        "请关闭 reply_merge，避免同一轮被合并两次"
                    )
                    return
        except Exception:
            pass


    @_on_waiting_llm_request()
    async def gal_debounce(self, event: AstrMessageEvent):
        """Merge consecutive gal messages from one user into one LLM request."""
        if not self.config.bool("gal_debounce_enabled", True):
            return
        key = self._key(event)
        session = self.store.get(key)
        if session is None or session.mode != "gal":
            return
        if event.get_result() is not None:
            return
        text = self._trigger_text(event)
        if not text or text.startswith("/"):
            return
        self_id = str(event.get_self_id() or "")
        if self_id and str(event.get_sender_id() or "") == self_id:
            return

        now = time.monotonic()
        window = self._debounce_windows.get(key)
        if window is not None:
            window["texts"].append(text)
            window["last"] = now
            event.stop_event()
            return

        window = {"texts": [text], "start": now, "last": now}
        self._debounce_windows[key] = window
        quiet = self.config.float("gal_debounce_seconds", 1.0, 0.2, 5.0)
        max_wait = self.config.float("gal_debounce_max_seconds", 5.0, 1.0, 15.0)
        try:
            while True:
                await asyncio.sleep(0.15)
                now = time.monotonic()
                if now - window["last"] >= quiet or now - window["start"] >= max_wait:
                    break
                current = self.store.get(key)
                if current is None or current.mode != "gal":
                    break
        finally:
            self._debounce_windows.pop(key, None)

        texts = window["texts"]
        event.set_extra("_gal_primary_text", texts[0])
        event.set_extra("_gal_followups", texts[1:])
        event.set_extra("_gal_merged_text", " ".join(texts))
        if len(texts) > 1:
            logger.info("[gal] 防抖合并 %s 条消息 key=%s", len(texts), key)

    # ---------- 注入格式要求 / 处理选择 ----------

    def _append_system(self, req, hints: list[str]) -> None:
        if not hints:
            return
        current = (getattr(req, "system_prompt", "") or "").strip()
        req.system_prompt = (current + "\n\n" if current else "") + "\n".join(hints)

    @filter.on_llm_request()
    async def inject_choice(self, event: AstrMessageEvent, req):
        """把“玩家选了什么”和 gal 输出格式追加到 system prompt。"""
        try:
            key = self._key(event)
            session = self.store.get(key)
            if session is None or session.mode != "gal":
                return

            text = event.get_extra("_gal_primary_text") or self._trigger_text(event)
            followups = event.get_extra("_gal_followups") or []
            hints: list[str] = []

            if text and is_exit_intent(" ".join([text, *followups]), self._exit_words()):
                await self._exit(event, session)
                hints.append(EXIT_HINT)
                await self.store.save()
                self._append_system(req, hints)
                return

            if session.just_entered:
                hints.append(ENTRY_HINT)
                if text and not phrase_hit(text, _GENERIC_START):
                    hints.append(f"玩家说「{text}」，就从这句话切入开场。")
            else:
                options = [item for item in session.options if item]
                pick = match_option(text, options) if text else OptionMatch()
                if pick.index is not None and not pick.ambiguous:
                    option = options[pick.index]
                    hints.append(PICK_HINT.format(option=option))
                    session.remember(f"第 {max(1, session.turn_id)} 幕：选了「{option}」")
                elif pick.ambiguous and pick.index is not None and pick.second_index is not None:
                    hints.append(
                        AMBIGUOUS_HINT.format(
                            a=options[pick.index],
                            b=options[pick.second_index],
                        )
                    )
                elif pick.free:
                    hints.append(FREE_SLOT_HINT)
                elif not text:
                    hints.append(MEDIA_HINT)
                elif options:
                    hints.append(FREE_HINT.format(text=text))
                else:
                    hints.append(NO_OPTIONS_HINT)

            if session.history:
                hints.append("前几幕的选择：" + "；".join(session.history[-5:]) + "。保持剧情连续。")
            if followups:
                hints.append(
                    "玩家在你回复前又连续补充了："
                    + " / ".join(followups)
                    + "。把这些和主消息看成同一轮，先回应补充内容，再给新选项。"
                )
            if session.script:
                hints.append(script_brief(session.script, session.turn_id))
            hints.append(tone_hint(session.affection))
            hints.append(
                f"你就是「{self._bot_label()}」本人，用这个身份直接对玩家说话；"
                "所有 <say> 必须是你开口说出的台词，禁止旁白、小说叙述、动作/环境描写；"
                "不要称呼玩家为“用户”，也不要跳出角色解释规则。"
            )
            hints.append(GAL_RULES)
            self._append_system(req, hints)
            # gal 模式只产出「表情 + 台词 + 选项」，临时关掉工具调用，
            # 避免中间步骤的文字被误渲染成一张图。
            if hasattr(req, "func_tool"):
                try:
                    req.func_tool = None
                except Exception:
                    pass

            session.touch()
            await self.store.save()
            logger.debug(
                "[gal] 注入提示 key=%s turn=%s options=%s",
                key,
                session.turn_id,
                len(session.options),
            )
        except Exception as exc:
            logger.error("[gal] 提示注入失败: %s", exc, exc_info=True)

    # ---------- 出图 ----------

    @filter.on_decorating_result()
    async def decorate_result(self, event: AstrMessageEvent):
        """把纯文本回复替换成 GalGame 图片；失败时降级为可读文字。"""
        try:
            key = self._key(event)
            session = self.store.get(key)

            result = event.get_result()
            if result is None or not getattr(result, "chain", None):
                return
            if any(isinstance(component, Image) for component in result.chain):
                return

            text = "".join(
                component.text
                for component in result.chain
                if isinstance(component, Plain)
            ).strip()
            if not text:
                return

            if session is None or session.mode != "gal":
                # Group chats sometimes keep a gal-shaped answer in memory even
                # when the trigger was not recognized.  Never leak raw tags.
                if "<say>" not in text and "<opt>" not in text:
                    return
                session = self.store.get_or_create(key)
                session.mode = "gal"
                await self.store.save()
                logger.warning("[gal] 未进入模式但检测到 gal 标签，自动接管 key=%s", key)

            # 不要把模型思考过程插到图片前面
            event.set_extra("_llm_reasoning_content", "")

            # 只处理 LLM 结果；/gal status 之类的指令输出保持原样。
            # 旧版本或第三方 runner 可能把 LLM 结果标成 GENERAL_RESULT，
            # 所以带 <say>/<opt> 的文本仍然放行。
            is_llm_result = getattr(result, "is_llm_result", None)
            if callable(is_llm_result) and not is_llm_result():
                content_type = getattr(result, "result_content_type", None)
                if (
                    getattr(content_type, "name", "") != "STREAMING_FINISH"
                    and "<say>" not in text
                    and "<opt>" not in text
                ):
                    return

            parsed = parse_gal_reply(
                text,
                option_max_units=self.config.float("option_max_units", 16.0, 4, 30),
            )
            ending_info = None
            script = session.script if isinstance(session.script, dict) else {}
            if parsed.ending:
                ending_info = ending_by_id(script, parsed.ending)
            if len(parsed.options) < 2 and not ending_info:
                result.chain = [Plain(self._fallback_text(parsed.say, parsed.options))]
                logger.warning("[gal] 本轮选项不足 2 个，降级为文字")
                return

            async with self._lock_for(key):
                session.turn_id += 1
                old_affection = session.affection
                old_mood = session.mood
                old_delta = session.affection_delta
                delta = parsed.affection_delta
                if delta is None:
                    session.affection_delta = 0
                else:
                    delta = max(-5, min(5, int(delta)))
                    session.affection = clamp(session.affection + delta)
                    session.affection_delta = session.affection - old_affection
                session.mood = mood_for(parsed.emotion or session.emotion)
                quote = (
                    event.get_extra("gal_quote")
                    or event.get_extra("_gal_merged_text")
                    or clean_message(event.message_str).strip()
                )
                try:
                    template, data = self.renderer.build(
                        session=session,
                        quote=quote,
                        options=parsed.options,
                        say=parsed.say,
                        emotion=parsed.emotion,
                        speaker=event.get_sender_name() or "",
                        user_id=str(event.get_sender_id() or ""),
                        lines=parsed.lines or None,
                        option_meta=parsed.option_meta,
                        ending=ending_info,
                    )
                    image = await render_image(
                        self,
                        self.config,
                        template,
                        data,
                        options={
                            "type": "jpeg",
                            "quality": self.config.int("image_quality", 90, 30, 100),
                            "timeout": 15000,
                            "scale": "css",
                            "animations": "disabled",
                        },
                        timeout=90,
                    )
                except Exception as exc:
                    session.turn_id = max(0, session.turn_id - 1)
                    session.affection = old_affection
                    session.mood = old_mood
                    session.affection_delta = old_delta
                    logger.error("[gal] 出图失败: %s", exc, exc_info=True)
                    result.chain = [Plain(self._fallback_text(parsed.say, parsed.options))]
                    return

                if not image:
                    session.turn_id = max(0, session.turn_id - 1)
                    session.affection = old_affection
                    session.mood = old_mood
                    session.affection_delta = old_delta
                    result.chain = [Plain(self._fallback_text(parsed.say, parsed.options))]
                    logger.warning("[gal] 出图返回空结果，降级为文字")
                    return

                if image.startswith("http"):
                    component = Image.fromURL(image)
                elif image.startswith("file:///"):
                    component = Image(file=image)
                else:
                    component = Image.fromFileSystem(image)
                result.chain = [component]
                session.options = parsed.options[:4]
                session.option_meta = parsed.option_meta[:4]
                session.quote = quote
                session.emotion = parsed.emotion
                session.just_entered = False
                session.options_at = time.time()
                if ending_info:
                    session.ending_id = str(ending_info.get("id") or parsed.ending)
                    session.ending_title = str(ending_info.get("name") or "结局")
                    session.ended = True
                    session.mode = "ended"
                    session.options = []
                    session.option_meta = []
                session.touch()
                await self.store.save()

                if parsed.lines:
                    self._pending_voice[key] = (parsed.lines, time.time())
                elif parsed.say:
                    self._pending_voice[key] = (
                        [GalLine(say=parsed.say, emotion=parsed.emotion)],
                        time.time(),
                    )
                logger.info(
                    "[gal] 出图完成 key=%s turn=%s options=%s lines=%s emotion=%s",
                    key,
                    session.turn_id,
                    len(session.options),
                    len(parsed.lines) or 1,
                    parsed.emotion or "默认",
                )
        except Exception as exc:
            logger.error("[gal] 结果装饰失败: %s", exc, exc_info=True)

    # ---------- 配音 ----------

    @filter.after_message_sent()
    async def send_voice_after_image(self, event: AstrMessageEvent):
        """图片发出后再补一条角色语音，避免语音先于图片到达。"""
        try:
            key = self._key(event)
            item = self._pending_voice.pop(key, None)
            if not item:
                return
            lines, created_at = item
            if time.time() - created_at > 120:
                return
            session = self.store.get(key)
            if session is None or session.mode not in {"gal", "ended"}:
                return
            await self.voice.speak(event, lines, session)
        except Exception as exc:
            logger.warning("[gal] 配音发送失败: %s", exc)

    async def terminate(self):
        # 插件被停用/重载时，把还在 gal 模式里的会话恢复到原模型
        try:
            from astrbot.core.provider.entities import ProviderType
        except Exception:
            ProviderType = None
        if ProviderType is not None:
            for session in self.store.sessions():
                previous = (session.prev_provider_id or "").strip()
                if session.mode != "gal" or not previous:
                    continue
                umo = session.key.rsplit("|", 1)[0]
                try:
                    await self.context.provider_manager.set_provider(
                        previous,
                        ProviderType.CHAT_COMPLETION,
                        umo,
                    )
                    session.prev_provider_id = ""
                except Exception as exc:
                    logger.warning("[gal] 终止时恢复模型 %s 失败: %s", previous, exc)
        try:
            await self.store.flush()
        except Exception as exc:
            logger.warning("[gal] 终止时保存状态失败: %s", exc)
        self._locks.clear()
        self._pending_voice.clear()
        self._debounce_windows.clear()
        try:
            from .core.browser_render import close_browser

            await close_browser()
        except Exception:
            pass


# Backward-compatible alias for tests / external imports.
GalChoice = GalChoicePlugin
