# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small JSON save-slot store for gal sessions (no database)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from astrbot.api import logger

from .config import plugin_data_dir
from .state import Session


class SaveStore:
    def __init__(self, max_slots: int = 10):
        self.path = plugin_data_dir("astrbot_plugin_gal_choice") / "saves.json"
        self.max_slots = max(1, int(max_slots))
        self._lock = asyncio.Lock()
        self._data: dict[str, dict[str, dict]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.is_file():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._data = {
                        str(user): slots
                        for user, slots in data.items()
                        if isinstance(slots, dict)
                    }
        except Exception as exc:
            logger.warning("[gal] 读取存档失败，忽略旧存档: %s", exc)
            self._data = {}

    def _write_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _name(value: str) -> str:
        name = (value or "").strip().replace("\n", " ").replace("\r", " ")
        return name[:20] or "存档"

    def list(self, user: str) -> list[dict]:
        slots = self._data.get(user, {})
        return sorted(
            (
                {
                    "name": name,
                    "saved_at": item.get("saved_at", 0),
                    "turn": item.get("session", {}).get("turn_id", 0),
                    "affection": item.get("session", {}).get("affection", 50),
                }
                for name, item in slots.items()
                if isinstance(item, dict)
            ),
            key=lambda item: item["saved_at"],
            reverse=True,
        )

    async def save(self, user: str, name: str, session: Session) -> str:
        async with self._lock:
            slots = self._data.setdefault(user, {})
            clean = self._name(name)
            if clean not in slots and len(slots) >= self.max_slots:
                oldest = min(slots.items(), key=lambda kv: kv[1].get("saved_at", 0))[0]
                slots.pop(oldest, None)
            slots[clean] = {
                "saved_at": time.time(),
                "session": session.to_dict(),
            }
            self._write_sync()
            return clean

    async def load(self, user: str, name: str) -> dict | None:
        async with self._lock:
            item = self._data.get(user, {}).get(self._name(name))
            if not isinstance(item, dict):
                return None
            session = item.get("session")
            return dict(session) if isinstance(session, dict) else None

    async def delete(self, user: str, name: str) -> bool:
        async with self._lock:
            slots = self._data.get(user, {})
            removed = slots.pop(self._name(name), None) is not None
            if removed:
                self._write_sync()
            return removed
