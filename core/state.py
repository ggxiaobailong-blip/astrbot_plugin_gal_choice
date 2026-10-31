# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-session GalGame state with TTL, atomic persistence and a size cap."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from astrbot.api import logger


@dataclass
class Session:
    key: str
    mode: str = "chat"
    options: list[str] = field(default_factory=list)
    quote: str = ""
    emotion: str = ""
    turn_id: int = 0
    just_entered: bool = False
    history: list[str] = field(default_factory=list)
    bg: str = ""
    provider_id: str = ""
    prev_provider_id: str = ""
    voice_enabled: bool | None = None
    options_at: float = 0.0
    affection: int = 50
    mood: str = "calm"
    affection_delta: int = 0
    script: dict = field(default_factory=dict)
    option_meta: list[dict] = field(default_factory=list)
    ending_id: str = ""
    ending_title: str = ""
    ended: bool = False
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def remember(self, text: str, limit: int = 8) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.history.append(text)
        if len(self.history) > limit:
            self.history = self.history[-limit:]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "options": list(self.options),
            "quote": self.quote,
            "emotion": self.emotion,
            "turn_id": self.turn_id,
            "just_entered": self.just_entered,
            "history": list(self.history[-8:]),
            "bg": self.bg,
            "provider_id": self.provider_id,
            "prev_provider_id": self.prev_provider_id,
            "voice_enabled": self.voice_enabled,
            "options_at": self.options_at,
            "affection": self.affection,
            "mood": self.mood,
            "affection_delta": self.affection_delta,
            "script": self.script,
            "option_meta": self.option_meta,
            "ending_id": self.ending_id,
            "ending_title": self.ending_title,
            "ended": self.ended,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, key: str, data: dict) -> "Session":
        options = data.get("options") if isinstance(data.get("options"), list) else []
        history = data.get("history") if isinstance(data.get("history"), list) else []
        voice = data.get("voice_enabled")
        return cls(
            key=key,
            mode="gal" if data.get("mode") == "gal" else "chat",
            options=[str(item) for item in options if isinstance(item, str)][:4],
            quote=str(data.get("quote") or ""),
            emotion=str(data.get("emotion") or ""),
            turn_id=max(0, int(data.get("turn_id") or 0)),
            just_entered=bool(data.get("just_entered")),
            history=[str(item) for item in history if isinstance(item, str)][-8:],
            bg=str(data.get("bg") or ""),
            provider_id=str(data.get("provider_id") or ""),
            prev_provider_id=str(data.get("prev_provider_id") or ""),
            voice_enabled=voice if isinstance(voice, bool) else None,
            options_at=float(data.get("options_at") or data.get("updated_at") or 0),
            affection=max(0, min(100, int(data["affection"] if data.get("affection") is not None else 50))),
            mood=str(data.get("mood") or "calm"),
            affection_delta=int(data.get("affection_delta") or 0),
            script=dict(data.get("script") or {}) if isinstance(data.get("script"), dict) else {},
            option_meta=[
                dict(item)
                for item in (data.get("option_meta") or [])
                if isinstance(item, dict)
            ][:4],
            ending_id=str(data.get("ending_id") or ""),
            ending_title=str(data.get("ending_title") or ""),
            ended=bool(data.get("ended")),
            updated_at=float(data.get("updated_at") or time.time()),
        )


class SessionStore:
    def __init__(
        self,
        path: Path | None,
        idle_seconds: int = 7200,
        option_ttl: int = 600,
        max_sessions: int = 500,
    ):
        self.path = Path(path) if path else None
        self.idle_seconds = max(60, int(idle_seconds))
        self.option_ttl = max(30, int(option_ttl))
        self.max_sessions = max(20, int(max_sessions))
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._load()

    # ---------- read ----------

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[gal] 读取状态失败，忽略旧状态: %s", exc)
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, dict):
                try:
                    self._sessions[key] = Session.from_dict(key, value)
                except Exception:
                    continue
        self._prune()

    def _is_expired(self, session: Session, now: float) -> bool:
        if session.mode == "gal":
            limit = self.idle_seconds
        elif session.mode == "ended":
            limit = max(self.idle_seconds, 24 * 3600)
        elif session.options:
            limit = self.option_ttl
        else:
            limit = max(300, self.option_ttl // 2)
        return now - session.updated_at > limit

    def get(self, key: str) -> Session | None:
        session = self._sessions.get(key)
        if session is None:
            return None
        now = time.time()
        if self._is_expired(session, now):
            self._sessions.pop(key, None)
            return None
        if (
            session.mode == "gal"
            and session.options
            and session.options_at
            and now - session.options_at > self.option_ttl
        ):
            session.options = []
            session.options_at = 0.0
        return session

    def get_or_create(self, key: str) -> Session:
        session = self.get(key)
        if session is None:
            session = Session(key=key)
            self._sessions[key] = session
        return session

    def __len__(self) -> int:
        return len(self._sessions)

    def sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def remove(self, key: str) -> None:
        self._sessions.pop(key, None)

    def put(self, session: Session) -> None:
        self._sessions[session.key] = session

    # ---------- write ----------

    def _prune(self) -> dict[str, dict]:
        now = time.time()
        for key in [k for k, v in self._sessions.items() if self._is_expired(v, now)]:
            self._sessions.pop(key, None)
        if len(self._sessions) > self.max_sessions:
            ordered = sorted(self._sessions.values(), key=lambda s: s.updated_at)
            for session in ordered[: len(self._sessions) - self.max_sessions]:
                self._sessions.pop(session.key, None)
        return {key: session.to_dict() for key, session in self._sessions.items()}

    def _write_sync(self, data: dict[str, dict]) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    async def save(self) -> None:
        async with self._lock:
            data = self._prune()
            if not self.path:
                return
            try:
                await asyncio.to_thread(self._write_sync, data)
            except Exception as exc:
                logger.warning("[gal] 写入状态失败: %s", exc)

    async def flush(self) -> None:
        await self.save()
