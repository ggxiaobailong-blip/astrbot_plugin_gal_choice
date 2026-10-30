# SPDX-License-Identifier: AGPL-3.0-or-later
"""Text-to-speech delivery for the GalGame dialogue line."""

from __future__ import annotations

import asyncio
import base64
import io
import random
import re
import shutil
import time
from pathlib import Path

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Record

from .config import PluginConfig, plugin_data_dir
from .emotions import tag_marker

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover - local unit tests without AstrBot
    import logging

    logger = logging.getLogger("astrbot.plugin.gal_choice.voice")

try:
    import pysilk
except Exception:  # pragma: no cover - dependency is optional outside QQ
    pysilk = None

_TTS_TIMEOUT = 30
_PLUGIN_NAME = "astrbot_plugin_gal_choice"


class _SilkRecord(Record):
    """Record whose base64 payload stays SILK.

    AstrBot's stock Record.convert_to_base64() asks MediaResolver for WAV,
    which undoes our pre-encoding and makes NapCat's broken ntsilk ffmpeg run.
    Overriding it lets the regular MessageChain path carry the SILK bytes.
    """

    async def convert_to_base64(self) -> str:
        path = self.path or (
            self.file.removeprefix("file://") if self.file else ""
        )
        try:
            return base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError:
            return await super().convert_to_base64()



def clean_voice_text(text: str, limit: int = 200) -> str:
    """Strip markdown/plugin tags so the TTS engine does not read them out."""
    if not text:
        return ""
    value = re.sub(r"<[^>]{0,40}>", "", text)
    value = value.replace("＜", "").replace("＞", "")
    value = re.sub(r"\[[^\]]{0,80}\]", "", value)
    value = re.sub(r"&&[^&]{1,80}&&", "", value)
    value = re.sub(r"[*_`#>~|]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.strip("「」『』\"'“”‘’")
    return value[:limit].strip()


def _is_silk(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    return head.startswith(b"\x02#!SILK") or head.startswith(b"#!SILK")


def _encode_pcm_to_silk(pcm: bytes) -> bytes:
    if pysilk is None:
        return b""
    out = io.BytesIO()
    pysilk.encode(io.BytesIO(pcm), out, 24000, 24000, tencent=True)
    return out.getvalue()


class VoiceService:
    def __init__(self, context, config: PluginConfig):
        self.context = context
        self.config = config
        self._silk_warned = False

    def _provider(self, umo: str):
        provider_id = self.config.str("tts_provider_id")
        provider = None
        if provider_id:
            try:
                provider = self.context.get_provider_by_id(provider_id)
            except Exception as exc:
                logger.warning("[gal] 取指定 TTS 提供商失败: %s", exc)
        if provider is None or not hasattr(provider, "get_audio"):
            try:
                provider = self.context.get_using_tts_provider(umo)
            except Exception as exc:
                logger.warning("[gal] 取全局 TTS 提供商失败: %s", exc)
                provider = None
        return provider

    @staticmethod
    def _provider_type(provider) -> str:
        try:
            meta = provider.meta()
            return str(getattr(meta, "type", "") or "")
        except Exception:
            return provider.__class__.__name__

    def _emotion_tag(self, provider, emotion: str) -> str:
        mode = self.config.str("tts_emotion_mode", "auto").lower()
        if mode == "off":
            return ""
        if mode == "auto" and "fish" not in self._provider_type(provider).lower():
            return ""
        return tag_marker(emotion)

    async def _to_silk(self, audio: str) -> str | None:
        """Convert TTS audio to Tencent SILK for NapCat.

        NapCat's bundled ffmpeg does not ship the ``ntsilk_s16le`` encoder, so
        passing a WAV/MP3 to NapCat fails with "Requested output format
        'ntsilk_s16le' is not a suitable output format".  Pre-encoding here
        makes NapCat skip its own conversion.
        """
        if audio.startswith("http://") or audio.startswith("https://"):
            logger.warning("[gal] TTS 返回网络音频，QQ 语音需要本地 silk，跳过配音")
            return None
        src = Path(audio)
        if not src.is_file():
            logger.warning("[gal] TTS 音频不存在: %s", src)
            return None
        if _is_silk(src):
            return str(src)
        if pysilk is None:
            if not self._silk_warned:
                self._silk_warned = True
                logger.warning("[gal] 未安装 silk-python，无法为 QQ 预转 silk；请 pip install silk-python")
            return None

        ffmpeg = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        if not Path(ffmpeg).exists():
            logger.warning("[gal] 找不到 ffmpeg，无法把 TTS 音频转成 silk")
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-i",
                str(src),
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                "24000",
                "pipe:1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            pcm, err = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0 or not pcm:
                logger.warning("[gal] 音频转 PCM 失败: %s", (err or b"")[:300])
                return None
            data = await asyncio.wait_for(
                asyncio.to_thread(_encode_pcm_to_silk, pcm),
                timeout=30,
            )
        except Exception as exc:
            logger.warning("[gal] 音频转 silk 失败: %s", exc)
            return None
        if not data.startswith(b"\x02#!SILK") and not data.startswith(b"#!SILK"):
            logger.warning("[gal] silk 编码结果不合法，跳过配音")
            return None

        try:
            cache = plugin_data_dir(_PLUGIN_NAME) / "voice_cache"
            cache.mkdir(parents=True, exist_ok=True)
            out = cache / f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}.silk"
            out.write_bytes(data)
            for old in sorted(cache.glob("*.silk"), key=lambda p: p.stat().st_mtime)[:-30]:
                try:
                    old.unlink()
                except OSError:
                    pass
            return str(out)
        except Exception as exc:
            logger.warning("[gal] 保存 silk 失败: %s", exc)
            return None

    async def speak(self, event, text: str, emotion: str, session) -> None:
        enabled = (
            session.voice_enabled
            if isinstance(session.voice_enabled, bool)
            else self.config.bool("voice_enabled", True)
        )
        if not enabled:
            return
        if random.random() > self.config.float("voice_probability", 1.0, 0.0, 1.0):
            return

        body = clean_voice_text(text)
        if not body:
            return

        provider = self._provider(event.unified_msg_origin)
        if provider is None:
            logger.info("[gal] 没有可用的 TTS 提供商，跳过配音")
            return

        tag = self._emotion_tag(provider, emotion)
        payload = f"{tag} {body}".strip() if tag else body
        try:
            audio = await asyncio.wait_for(provider.get_audio(payload), timeout=_TTS_TIMEOUT)
        except Exception as exc:
            logger.warning("[gal] TTS 生成失败: %s", exc)
            return
        if not audio:
            logger.warning("[gal] TTS 返回空音频: %s", body[:30])
            return
        audio = str(audio)

        platform = (event.get_platform_name() or "").lower()
        umo = event.unified_msg_origin or ""
        is_qq = platform.startswith("aiocqhttp") or umo.startswith("bot:")
        if is_qq:
            audio = await self._to_silk(audio) or ""
            if not audio:
                logger.warning("[gal] QQ 语音未发送：silk 转换失败")
                return

        try:
            if is_qq:
                path = Path(audio).resolve()
                record = _SilkRecord(
                    file=path.as_uri(),
                    path=str(path),
                    text=body,
                )
            elif audio.startswith("http://") or audio.startswith("https://"):
                record = Record.fromURL(audio, text=body)
            else:
                record = Record.fromFileSystem(audio, text=body)
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain([record]),
            )
            logger.info(
                "[gal] 配音已发送 %s 字（%s，platform=%s）",
                len(body),
                "silk" if is_qq else "原始音频",
                platform or "?",
            )
        except Exception as exc:
            logger.warning("[gal] 配音发送失败: %s", exc)
