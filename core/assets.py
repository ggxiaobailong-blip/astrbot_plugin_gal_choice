# SPDX-License-Identifier: AGPL-3.0-or-later
"""User asset library: character sprites, backgrounds and per-character layout.

Built-in assets stay in the plugin package.  Everything uploaded by a user is
stored below ``data/plugin_data/astrbot_plugin_gal_choice/`` so plugin updates
never wipe it.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import (
    ASSETS_DIR,
    BACKGROUND_DIR,
    PluginConfig,
    plugin_data_dir,
    safe_asset,
)
from .emotions import (
    EMOTION_IDS,
    emotion_groups,
    group_for,
    known_emotion,
)

from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_gal_choice"
EMOTIONS = EMOTION_IDS
DEFAULT_LAYOUT = {
    "left": 31.0,
    "top": 22,
    "height": 907,
    "max_width": 62.0,
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
_CUSTOM_ID_RE = re.compile(r"^custom_[0-9a-f]{8}$")
_BUILTIN_FALLBACK = {
    "happy": "happy",
    "excited": "happy",
    "calm": "happy",
    "sad": "calm",
    "angry": "angry",
    "surprised": "surprised",
    "shy": "worried",
    "scared": "surprised",
    "worried": "worried",
    "tired": "calm",
    "gentle": "happy",
    "proud": "happy",
    "confused": "worried",
    "indifferent": "calm",
    "teasing": "happy",
    "moved": "happy",
    "disgusted": "angry",
    "curious": "surprised",
}


def _clamp(value, low, high, default):
    try:
        value = type(default)(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def normalize_layout(raw) -> dict:
    data = raw if isinstance(raw, dict) else {}
    return {
        "left": _clamp(data.get("left", DEFAULT_LAYOUT["left"]), 0, 100, 31.0),
        "top": _clamp(data.get("top", DEFAULT_LAYOUT["top"]), -400, 900, 22),
        "height": _clamp(data.get("height", DEFAULT_LAYOUT["height"]), 120, 2200, 907),
        "max_width": _clamp(
            data.get("max_width", DEFAULT_LAYOUT["max_width"]), 10, 100, 62.0
        ),
    }


def _safe_upload_name(filename: str | None) -> tuple[str, str]:
    suffix = Path(filename or "upload.webp").suffix.lower()
    if suffix not in IMAGE_EXTS:
        suffix = ".webp"
    return suffix, uuid.uuid4().hex[:8]


def _is_image(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return False
    if head.startswith(b"\xff\xd8\xff"):  # jpeg
        return True
    if head.startswith(b"\x89PNG\r\n\x1a\n"):  # png
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return False


@dataclass
class CharacterProfile:
    id: str
    name: str
    builtin: bool = False
    sprites: dict[str, str] = field(default_factory=dict)
    default_sprite: str = ""
    layout: dict = field(default_factory=lambda: dict(DEFAULT_LAYOUT))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "builtin": self.builtin,
            "sprites": dict(self.sprites),
            "default_sprite": self.default_sprite,
            "layout": normalize_layout(self.layout),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterProfile":
        sprites_raw = data.get("sprites") if isinstance(data.get("sprites"), dict) else {}
        sprites: dict[str, str] = {}
        for emotion, filename in sprites_raw.items():
            if (
                isinstance(emotion, str)
                and isinstance(filename, str)
                and Path(filename).name == filename
                and Path(filename).suffix.lower() in IMAGE_EXTS
            ):
                sprites[group_for(emotion)] = filename
        default_sprite = data.get("default_sprite")
        if not isinstance(default_sprite, str) or Path(default_sprite).name != default_sprite:
            default_sprite = ""
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or "未命名角色")[:40],
            builtin=False,
            sprites=sprites,
            default_sprite=default_sprite,
            layout=normalize_layout(data.get("layout")),
        )


class AssetStore:
    def __init__(self, config: PluginConfig, data_dir: Path | None = None):
        self.config = config
        self.data_dir = Path(data_dir) if data_dir else plugin_data_dir(PLUGIN_NAME)
        self.assets_dir = self.data_dir / "assets"
        self.characters_dir = self.assets_dir / "characters"
        self.backgrounds_dir = self.assets_dir / "backgrounds"
        self.state_path = self.data_dir / "characters.json"
        self._thumbs: dict[tuple[str, int, int], str] = {}
        self._ensure_dirs()
        self._state = self._load()

    # ---------- persistence ----------

    def _ensure_dirs(self) -> None:
        for path in (self.data_dir, self.assets_dir, self.characters_dir, self.backgrounds_dir):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def _load(self) -> dict:
        state = {
            "active": "builtin",
            "builtin_layout": dict(DEFAULT_LAYOUT),
            "characters": [],
        }
        if not self.state_path.is_file():
            return state
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[gal] 读取 characters.json 失败，使用默认角色: %s", exc)
            return state
        if not isinstance(raw, dict):
            return state

        state["builtin_layout"] = normalize_layout(raw.get("builtin_layout"))
        characters: list[CharacterProfile] = []
        for item in raw.get("characters") or []:
            if not isinstance(item, dict):
                continue
            profile = CharacterProfile.from_dict(item)
            if not _CUSTOM_ID_RE.match(profile.id):
                continue
            if not (self.characters_dir / profile.id).is_dir():
                continue
            characters.append(profile)
        state["characters"] = characters
        active = raw.get("active")
        if active == "builtin" or any(p.id == active for p in characters):
            state["active"] = active
        return state

    def _save(self) -> None:
        payload = {
            "active": self._state["active"],
            "builtin_layout": normalize_layout(self._state["builtin_layout"]),
            "characters": [
                profile.to_dict()
                for profile in self._state["characters"]
                if isinstance(profile, CharacterProfile)
            ],
        }
        try:
            tmp = self.state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as exc:
            logger.warning("[gal] 保存 characters.json 失败: %s", exc)

    # ---------- profiles ----------

    def builtin_profile(self) -> CharacterProfile:
        sprites: dict[str, str] = {}
        for emotion, filename in self.config.emotion_map().items():
            if isinstance(filename, str) and filename:
                sprites[group_for(emotion)] = filename
        return CharacterProfile(
            id="builtin",
            name="内置角色",
            builtin=True,
            sprites=sprites,
            default_sprite=self.config.str("emotion_default_file", "whale_girl_moe.webp"),
            layout=dict(self._state.get("builtin_layout") or DEFAULT_LAYOUT),
        )

    def profiles(self) -> list[CharacterProfile]:
        return [self.builtin_profile(), *self._state["characters"]]

    def get(self, profile_id: str) -> CharacterProfile | None:
        if profile_id == "builtin":
            return self.builtin_profile()
        for profile in self._state["characters"]:
            if profile.id == profile_id:
                return profile
        return None

    def active(self) -> CharacterProfile:
        return self.get(self._state["active"]) or self.builtin_profile()

    def activate(self, profile_id: str) -> CharacterProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise ValueError("角色不存在")
        self._state["active"] = profile.id
        self._save()
        return profile

    def create(self, name: str) -> CharacterProfile:
        name = (name or "").strip()[:40] or "新角色"
        profile_id = f"custom_{uuid.uuid4().hex[:8]}"
        profile = CharacterProfile(
            id=profile_id,
            name=name,
            sprites={},
            default_sprite="",
            layout=dict(DEFAULT_LAYOUT),
        )
        (self.characters_dir / profile_id).mkdir(parents=True, exist_ok=True)
        self._state["characters"].append(profile)
        self._state["active"] = profile_id
        self._save()
        return profile

    def update(
        self,
        profile_id: str,
        name: str | None = None,
        layout: dict | None = None,
        sprites: dict | None = None,
        default_sprite: str | None = None,
    ) -> CharacterProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise ValueError("角色不存在")
        if profile.builtin:
            if layout is not None:
                self._state["builtin_layout"] = normalize_layout(layout)
                self._save()
            return self.builtin_profile()
        if name is not None:
            profile.name = name.strip()[:40] or profile.name
        if layout is not None:
            profile.layout = normalize_layout(layout)
        if sprites is not None:
            clean: dict[str, str] = {}
            for emotion, filename in sprites.items():
                if (
                    isinstance(emotion, str)
                    and isinstance(filename, str)
                    and Path(filename).name == filename
                    and Path(filename).suffix.lower() in IMAGE_EXTS
                ):
                    clean[group_for(emotion)] = filename
            profile.sprites = clean
        if default_sprite is not None:
            if (
                isinstance(default_sprite, str)
                and Path(default_sprite).name == default_sprite
                and Path(default_sprite).suffix.lower() in IMAGE_EXTS
            ):
                profile.default_sprite = default_sprite
            elif not default_sprite:
                profile.default_sprite = ""
        self._save()
        return profile

    def delete(self, profile_id: str) -> None:
        if profile_id == "builtin":
            raise ValueError("内置角色不能删除")
        profile = self.get(profile_id)
        if profile is None:
            raise ValueError("角色不存在")
        self._state["characters"] = [p for p in self._state["characters"] if p.id != profile_id]
        if self._state["active"] == profile_id:
            self._state["active"] = "builtin"
        shutil.rmtree(self.characters_dir / profile_id, ignore_errors=True)
        self._save()

    def save_layout(self, profile_id: str, layout: dict) -> CharacterProfile:
        return self.update(profile_id, layout=layout)

    # ---------- sprites / backgrounds ----------

    def profile_dir(self, profile_id: str) -> Path | None:
        if not _CUSTOM_ID_RE.match(profile_id or ""):
            return None
        path = (self.characters_dir / profile_id).resolve()
        try:
            path.relative_to(self.characters_dir.resolve())
        except ValueError:
            return None
        return path if path.is_dir() else None

    def resolve_sprite(self, profile: CharacterProfile, emotion: str) -> Path | None:
        raw_emotion = (emotion or "").strip().lower()
        if raw_emotion == "default":
            if profile.builtin:
                return self.config.asset(
                    profile.default_sprite
                    or self.config.str("emotion_default_file", "whale_girl_moe.webp")
                )
            base = self.profile_dir(profile.id)
            if base is not None and profile.default_sprite:
                path = safe_asset(base, profile.default_sprite)
                if path:
                    return path
            return self.config.asset(self.config.str("emotion_default_file", "whale_girl_moe.webp"))
        emotion = group_for(emotion)
        if profile.builtin:
            mapping = {
                group_for(key): value
                for key, value in self.config.emotion_map().items()
            }
            default_rel = self.config.str("emotion_default_file", "whale_girl_moe.webp")
            fallback_group = _BUILTIN_FALLBACK.get(emotion, "")
            rel = (
                mapping.get(emotion)
                or mapping.get(fallback_group)
                or profile.default_sprite
                or default_rel
            )
            path = self.config.asset(rel)
            if path:
                return path
            path = self.config.asset(default_rel)
            if path:
                return path
            return self.config.asset("whale_girl_moe.webp")
        base = self.profile_dir(profile.id)
        if base is None:
            return self.config.asset(self.config.str("emotion_default_file", "whale_girl_moe.webp"))
        rel = profile.sprites.get(emotion) or profile.default_sprite
        if rel:
            path = safe_asset(base, rel)
            if path:
                return path
        for candidate in (profile.default_sprite, *profile.sprites.values()):
            path = safe_asset(base, candidate)
            if path:
                return path
        return self.config.asset(self.config.str("emotion_default_file", "whale_girl_moe.webp"))

    async def save_sprite(self, profile_id: str, emotion: str, upload) -> CharacterProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise ValueError("角色不存在")
        if profile.builtin:
            raise ValueError("内置角色只读，请先新建一个角色再上传立绘")
        base = self.profile_dir(profile_id)
        if base is None:
            raise ValueError("角色目录不存在")
        raw_emotion = (emotion or "").strip().lower()
        if raw_emotion == "default":
            group_id = "default"
        elif known_emotion(emotion):
            group_id = group_for(emotion)
        else:
            raise ValueError("不支持的情绪，请从情绪列表里选择")
        suffix, token = _safe_upload_name(getattr(upload, "filename", ""))
        target = base / f"emo_{group_id}_{token}{suffix}"
        await upload.save(target, max_bytes=MAX_UPLOAD_BYTES)
        if not _is_image(target):
            try:
                target.unlink()
            except OSError:
                pass
            raise ValueError("上传的文件不是可识别的图片")
        if group_id == "default":
            profile.default_sprite = target.name
        else:
            profile.sprites[group_id] = target.name
            if not profile.default_sprite:
                profile.default_sprite = target.name
        self._save()
        return profile

    def bind_sprite(self, profile_id: str, emotion: str, filename: str) -> CharacterProfile:
        """Share one already-uploaded sprite between several emotion tags."""
        profile = self.get(profile_id)
        if profile is None:
            raise ValueError("角色不存在")
        if profile.builtin:
            raise ValueError("内置角色只读")
        base = self.profile_dir(profile_id)
        if base is None:
            raise ValueError("角色目录不存在")
        if not known_emotion(emotion) and (emotion or "").strip().lower() != "default":
            raise ValueError("不支持的情绪")
        target = safe_asset(base, filename)
        if target is None:
            raise ValueError("立绘文件不存在")
        if (emotion or "").strip().lower() == "default":
            profile.default_sprite = target.name
        else:
            profile.sprites[group_for(emotion)] = target.name
        if not profile.default_sprite:
            profile.default_sprite = target.name
        self._save()
        return profile

    async def save_background(self, upload) -> str:
        suffix, token = _safe_upload_name(getattr(upload, "filename", ""))
        target = self.backgrounds_dir / f"bg_{token}{suffix}"
        await upload.save(target, max_bytes=MAX_UPLOAD_BYTES)
        if not _is_image(target):
            try:
                target.unlink()
            except OSError:
                pass
            raise ValueError("上传的文件不是可识别的图片")
        return f"custom/{target.name}"

    def _background_paths(self) -> list[tuple[str, str, str, Path]]:
        items: list[tuple[str, str, str, Path]] = []
        try:
            builtins = sorted(
                p for p in BACKGROUND_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
            )
        except OSError:
            builtins = []
        for path in builtins:
            items.append((f"builtin/{path.name}", path.stem, "builtin", path))
        try:
            customs = sorted(
                p for p in self.backgrounds_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
            )
        except OSError:
            customs = []
        for path in customs:
            items.append((f"custom/{path.name}", path.name, "custom", path))
        return items

    def background_names(self) -> list[str]:
        return [name for name, _label, _kind, _path in self._background_paths()]

    def list_backgrounds(self) -> list[dict]:
        return [
            {
                "name": name,
                "label": label,
                "kind": kind,
                "url": self.thumb_data_url(path),
            }
            for name, label, kind, path in self._background_paths()
        ]

    def resolve_background(self, name: str) -> Path | None:
        name = (name or "").strip()
        if not name:
            return None
        if name.startswith("custom/"):
            return safe_asset(self.backgrounds_dir, name[len("custom/") :])
        if name.startswith("builtin/"):
            return safe_asset(BACKGROUND_DIR, name[len("builtin/") :])
        return safe_asset(self.backgrounds_dir, name) or safe_asset(BACKGROUND_DIR, name)

    def delete_background(self, name: str) -> None:
        if not name.startswith("custom/"):
            raise ValueError("内置背景不能删除")
        path = safe_asset(self.backgrounds_dir, name[len("custom/") :])
        if path:
            path.unlink(missing_ok=True)

    # ---------- thumbnails / state ----------

    def thumb_data_url(self, path: Path | None, size: int = 320) -> str:
        if path is None or not path.is_file():
            return ""
        try:
            stat = path.stat()
        except OSError:
            return ""
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        cached = self._thumbs.get(key)
        if cached is not None:
            return cached
        try:
            from PIL import Image

            image = Image.open(path)
            image.thumbnail((size, size))
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=82, method=4)
            url = "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            try:
                mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
                url = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
            except OSError:
                return ""
        self._thumbs[key] = url
        return url

    def profile_state(self, profile: CharacterProfile) -> dict:
        sprites: dict[str, dict] = {}
        for group_id in EMOTIONS:
            path = self.resolve_sprite(profile, group_id)
            sprites[group_id] = {
                "file": profile.sprites.get(group_id, ""),
                "url": self.thumb_data_url(path),
                "fallback": not bool(profile.sprites.get(group_id)),
            }
        default_path = self.resolve_sprite(profile, "default")
        files: list[dict] = []
        if not profile.builtin:
            base = self.profile_dir(profile.id)
            if base is not None:
                used = {value: key for key, value in profile.sprites.items()}
                for path in sorted(base.iterdir()):
                    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                        continue
                    files.append(
                        {
                            "file": path.name,
                            "label": path.stem,
                            "url": self.thumb_data_url(path),
                            "group": used.get(path.name, ""),
                        }
                    )
        return {
            "id": profile.id,
            "name": profile.name,
            "builtin": profile.builtin,
            "sprites": sprites,
            "files": files,
            "default": {
                "file": profile.default_sprite,
                "url": self.thumb_data_url(default_path),
            },
            "layout": normalize_layout(profile.layout),
            "dir": str(self.profile_dir(profile.id)) if not profile.builtin else "",
        }

    def state(self) -> dict:
        active = self.active()
        active_background = self.config.str("background_file", "")
        if active_background and not active_background.startswith(("builtin/", "custom/")):
            if (BACKGROUND_DIR / active_background).is_file():
                active_background = f"builtin/{active_background}"
            elif (self.backgrounds_dir / active_background).is_file():
                active_background = f"custom/{active_background}"
        return {
            "active": active.id,
            "characters": [self.profile_state(p) for p in self.profiles()],
            "backgrounds": self.list_backgrounds(),
            "active_background": active_background,
            "background_mode": self.config.str("background_mode", "session"),
            "emotions": list(EMOTIONS),
            "emotion_groups": emotion_groups(),
            "settings": {
                "bot_label": self.config.str("bot_label", "小鲸鱼"),
                "default_say": self.config.str("default_say", "这几个方向，你想先聊哪个？"),
                "free_option_hint": self.config.str("free_option_hint", "✎ 自己说点什么…"),
                "box_alpha": self.config.float("box_alpha", 0.94, 0.2, 1.0),
                "image_quality": self.config.int("image_quality", 90, 30, 100),
                "render_backend": self.config.str("render_backend", "auto"),
                "render_endpoint": self.config.str("render_endpoint", ""),
                "dialogue_max_lines": self.config.int("dialogue_max_lines", 3, 1, 3),
                "voice_line_gap_ms": self.config.int("voice_line_gap_ms", 1000, 0, 2500),
                "gal_debounce_enabled": self.config.bool("gal_debounce_enabled", True),
                "gal_debounce_seconds": self.config.float("gal_debounce_seconds", 1.0, 0.2, 5.0),
                "gal_debounce_max_seconds": self.config.float("gal_debounce_max_seconds", 5.0, 1.0, 15.0),
            },
        }
