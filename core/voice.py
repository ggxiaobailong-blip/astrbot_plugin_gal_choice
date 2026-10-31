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
import wave
from pathlib import Path

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Record

from .config import PluginConfig, plugin_data_dir
from .emotions import tag_marker

from astrbot.api import logger

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

    async def _merge_audio(self, paths: list[str], gap_ms: int) -> str | None:
        cache = plugin_data_dir(_PLUGIN_NAME) / "voice_cache"
        cache.mkdir(parents=True, exist_ok=True)
        token = f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        ffmpeg = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        normalized: list[Path] = []
        for index, src in enumerate(paths, 1):
            if src.startswith("http://") or src.startswith("https://"):
                logger.warning("[gal] 语音行返回网络音频，无法合并: %s", src)
                continue
            source = Path(src)
            if not source.is_file():
                logger.warning("[gal] 语音行文件不存在: %s", source)
                continue
            target = cache / f"line_{token}_{index}.wav"
            try:
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg,
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-sample_fmt",
                    "s16",
                    str(target),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, err = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode != 0 or not target.is_file():
                    logger.warning("[gal] 语音行转 PCM 失败: %s", (err or b"")[:200])
                    continue
                normalized.append(target)
            except Exception as exc:
                logger.warning("[gal] 语音行转 PCM 异常: %s", exc)
        if not normalized:
            return None
        if len(normalized) == 1:
            return str(normalized[0])

        merged = cache / f"merged_{token}.wav"
        with wave.open(str(normalized[0]), "rb") as first:
            params = first.getparams()
        silence = b"\x00" * int(
            params.framerate
            * params.nchannels
            * params.sampwidth
            * max(0, gap_ms)
            / 1000
        )
        with wave.open(str(merged), "wb") as out:
            out.setnchannels(params.nchannels)
            out.setsampwidth(params.sampwidth)
            out.setframerate(params.framerate)
            for index, path in enumerate(normalized):
                with wave.open(str(path), "rb") as inp:
                    out.writeframes(inp.readframes(inp.getnframes()))
                if index < len(normalized) - 1:
                    out.writeframes(silence)
        return str(merged)

    async def speak(self, event, lines, session=None) -> None:
        # Backward compatibility for a single string + emotion tuple.
        if isinstance(lines, str):
            lines = [(lines, "")]
        if session is None:
            return
        enabled = (
            session.voice_enabled
            if isinstance(session.voice_enabled, bool)
            else self.config.bool("voice_enabled", True)
        )
        if not enabled:
            return
        if random.random() > self.config.float("voice_probability", 1.0, 0.0, 1.0):
            return

        items: list[tuple[str, str]] = []
        for item in lines or []:
            if isinstance(item, (tuple, list)):
                say, emotion = item[0], (item[1] if len(item) > 1 else "")
            else:
                say = getattr(item, "say", "")
                emotion = getattr(item, "emotion", "")
            body = clean_voice_text(str(say or ""))
            if body:
                items.append((body, str(emotion or "")))
        if not items:
            return

        provider = self._provider(event.unified_msg_origin)
        if provider is None:
            logger.info("[gal] 没有可用的 TTS 提供商，跳过配音")
            return

        async def synth(body: str, emotion: str) -> str:
            tag = self._emotion_tag(provider, emotion)
            payload = f"{tag} {body}".strip() if tag else body
            return await asyncio.wait_for(provider.get_audio(payload), timeout=_TTS_TIMEOUT)

        results = await asyncio.gather(
            *(synth(body, emotion) for body, emotion in items),
            return_exceptions=True,
        )
        paths: list[str] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("[gal] 单行 TTS 失败: %s", result)
            elif result:
                paths.append(str(result))
        if not paths:
            logger.warning("[gal] TTS 没有返回可用音频")
            return

        body_text = " ".join(body for body, _ in items)
        if len(paths) == 1:
            audio = paths[0]
        else:
            gap_ms = self.config.int("voice_line_gap_ms", 1000, 0, 2500)
            audio = await self._merge_audio(paths, gap_ms)
            if not audio:
                logger.warning("[gal] 多行语音合并失败，跳过本次配音")
                return

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
                    text=body_text,
                )
            elif audio.startswith("http://") or audio.startswith("https://"):
                record = Record.fromURL(audio, text=body_text)
            else:
                record = Record.fromFileSystem(audio, text=body_text)
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain([record]),
            )
            logger.info(
                "[gal] 配音已发送 %s 行/%s 字（%s，platform=%s）",
                len(paths),
                len(body_text),
                "silk" if is_qq else "合并音频",
                platform or "?",
            )
        except Exception as exc:
            logger.warning("[gal] 配音发送失败: %s", exc)

