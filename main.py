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
from astrbot.api.star import Context, Star, register

if __package__:
    from .core.assets import AssetStore
    from .core.config import PluginConfig, plugin_data_dir
    from .core.parser import (
        LETTERS,
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
    from .core.state import Session, SessionStore
    from .core.voice import VoiceService
    from .core.webui import GalWebUI
else:  # pragma: no cover - only used when running the file directly
    from core.assets import AssetStore
    from core.config import PluginConfig, plugin_data_dir
    from core.parser import (
        LETTERS,
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
    from core.state import Session, SessionStore
    from core.voice import VoiceService
    from core.webui import GalWebUI

PLUGIN_NAME = "astrbot_plugin_gal_choice"
_GENERIC_START = ("开始", "来吧", "随便", "你决定", "都行", "继续")


@register(PLUGIN_NAME, "iv小白龙", "GalGame 选项成图 + 配音 + 资源工作台", "0.3.10")
class GalChoice(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = PluginConfig(config)
        data_dir = plugin_data_dir(PLUGIN_NAME)
        self.store = SessionStore(
            data_dir / "sessions.json",
            idle_seconds=self.config.int("mode_idle_minutes", 120, 5, 7 * 24 * 60) * 60,
            option_ttl=self.config.int("option_ttl", 600, 30, 86400),
        )
        self.assets = AssetStore(self.config)
        self.renderer = Renderer(self.config, self.assets)
        self.voice = VoiceService(context, self.config)
        self.webui = GalWebUI(self, self.assets, self.renderer, self.config)
        self.webui.register()
        self._pending_voice: dict[str, tuple[str, str, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._provider_warned: set[str] = set()

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

    async def _enter(self, event: AstrMessageEvent, session: Session) -> None:
        session.mode = "gal"
        session.just_entered = True
        session.options = []
        session.quote = ""
        session.emotion = ""
        session.turn_id = 0
        session.history = []
        session.bg = ""
        session.options_at = 0.0
        session.touch()
        target = session.provider_id or self.config.str("gal_provider_id")
        if target:
            await self._switch_provider(event, session, target)

    async def _exit(self, event: AstrMessageEvent, session: Session) -> None:
        await self._restore_provider(event, session)
        session.mode = "chat"
        session.options = []
        session.quote = ""
        session.emotion = ""
        session.turn_id = 0
        session.just_entered = False
        session.history = []
        session.bg = ""
        session.options_at = 0.0
        session.touch()

    # ---------- 指令 ----------

    @filter.command("gal")
    async def gal(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        """GalGame 模式控制：/gal [start|stop|status|model|voice|reset|help]。"""
        key = self._key(event)
        session = self.store.get_or_create(key)
        action = (action or "").strip().lower()
        value = (value or "").strip()

        if not action or action in {"start", "begin", "开始", "进入"}:
            if session.mode == "gal":
                # gal_gate 可能已经在本条消息里进入模式；这时不重复提示，
                # 也不产出结果，让后面的 LLM 直接生成开场图。
                if session.just_entered:
                    event.set_extra("gal_quote", "开始")
                    return
                yield event.plain_result("已经在 GalGame 模式里了。选一个选项，或发送 /gal reset 重开。")
                return
            await self._enter(event, session)
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
            if session.mode != "gal":
                yield event.plain_result("当前是普通聊天模式。发送 /gal start 进入 GalGame 模式。")
                return
            lines = [
                "模式：GalGame",
                f"进度：{('第 ' + str(session.turn_id) + ' 幕') if session.turn_id else '序章'}",
            ]
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
            "/gal start         进入模式\n"
            "/gal stop          退出模式\n"
            "/gal status        查看当前状态\n"
            "/gal model <id>    指定模型；default 恢复跟随会话\n"
            "/gal voice on|off  开关台词语音\n"
            "/gal reset         清空本会话状态\n"
            "/gal help          查看帮助\n\n"
            "进入后回复 A/B/C/D 或 1/2/3/4 选择，回复 0 或直接说话则自由输入。"
        )

    # ---------- 消息闸门 ----------

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1000)
    async def gal_gate(self, event: AstrMessageEvent):
        """在 gal 会话里放行裸字母，并让群聊里的裸字母能够触发 LLM。"""
        try:
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
                await self._enter(event, session)
                await self.store.save()
                event.is_wake = True
                event.is_at_or_wake_command = True
                event.set_extra("enable_streaming", False)
                logger.info("[gal] 进入 gal 模式 key=%s", key)
        except Exception as exc:
            logger.error("[gal] 闸门判断失败: %s", exc, exc_info=True)

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

            text = self._trigger_text(event)
            hints: list[str] = []

            if text and is_exit_intent(text, self._exit_words()):
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
            if len(parsed.options) < 2:
                result.chain = [Plain(self._fallback_text(parsed.say, parsed.options))]
                logger.warning("[gal] 本轮选项不足 2 个，降级为文字")
                return

            async with self._lock_for(key):
                session.turn_id += 1
                quote = event.get_extra("gal_quote") or clean_message(event.message_str).strip()
                try:
                    template, data = self.renderer.build(
                        session=session,
                        quote=quote,
                        options=parsed.options,
                        say=parsed.say,
                        emotion=parsed.emotion,
                        speaker=event.get_sender_name() or "",
                        user_id=str(event.get_sender_id() or ""),
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
                    logger.error("[gal] 出图失败: %s", exc, exc_info=True)
                    result.chain = [Plain(self._fallback_text(parsed.say, parsed.options))]
                    return

                if not image:
                    session.turn_id = max(0, session.turn_id - 1)
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
                session.quote = quote
                session.emotion = parsed.emotion
                session.just_entered = False
                session.options_at = time.time()
                session.touch()
                await self.store.save()

                if parsed.say:
                    self._pending_voice[key] = (parsed.say, parsed.emotion, time.time())
                logger.info(
                    "[gal] 出图完成 key=%s turn=%s options=%s emotion=%s",
                    key,
                    session.turn_id,
                    len(session.options),
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
            say, emotion, created_at = item
            if time.time() - created_at > 120:
                return
            session = self.store.get(key)
            if session is None or session.mode != "gal":
                return
            await self.voice.speak(event, say, emotion, session)
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
