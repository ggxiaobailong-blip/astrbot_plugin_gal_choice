# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fast, offline Pillow renderer for the GalGame card.

The remote HTML-to-image pool is convenient but slow and can be unavailable.
This renderer draws the same 1280x720 scene locally so a gal turn never
depends on an external T2I service.
"""

from __future__ import annotations

import base64
import io
import math
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .config import PluginConfig, plugin_data_dir

W, H = 1280, 720
BOX_LEFT, BOX_TOP, BOX_W, BOX_H = 90, 497, 1100, 199
OPT_LEFT, OPT_W, OPT_H = 800, 380, 50

_ASSET_FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "DroidSansFallback.ttf"
_FONT_CANDIDATES = [
    _ASSET_FONT,
    Path("/usr/share/fonts/google-droid/DroidSansFallback.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}
_INK = (18, 36, 58, 255)
_BLUE = (43, 115, 216, 255)
_MUTED = (124, 147, 171, 255)
_WHITE = (255, 255, 255, 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    size = max(8, int(size))
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for candidate in _FONT_CANDIDATES:
        try:
            if candidate.is_file():
                font = ImageFont.truetype(str(candidate), size)
                _FONT_CACHE[size] = font
                return font
        except Exception:
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def _data_image(value: str) -> Image.Image | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        if value.startswith("data:"):
            _, encoded = value.split(",", 1)
            raw = base64.b64decode(encoded)
        elif value.startswith("file://"):
            raw = Path(value[7:]).read_bytes()
        elif value.startswith("http://") or value.startswith("https://"):
            return None
        else:
            path = Path(value)
            if not path.is_file():
                return None
            raw = path.read_bytes()
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return None


def _cover(image: Image.Image, width: int = W, height: int = H) -> Image.Image:
    image = image.convert("RGB")
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height)).convert("RGBA")


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    text = str(text or "").replace("✎", "").replace("✏", "").replace("›", ">").strip()
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _shadow_round(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill,
    offset: int = 5,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(
        (x1 + offset, y1 + offset, x2 + offset, y2 + offset),
        radius=radius,
        fill=(0, 0, 0, 62),
    )
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _draw_dashed_rect(draw: ImageDraw.ImageDraw, box, color, width=2, dash=7) -> None:
    x1, y1, x2, y2 = box
    for x in range(x1, x2, dash * 2):
        draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=width)
        draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=width)
    for y in range(y1, y2, dash * 2):
        draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=width)
        draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=width)


def _draw_background(canvas: Image.Image, data: dict) -> None:
    bg = _data_image(data.get("bg_url", ""))
    if bg is None:
        grad = Image.new("RGBA", (W, H), (10, 18, 32, 255))
        draw = ImageDraw.Draw(grad)
        for y in range(H):
            ratio = y / H
            draw.line(
                (0, y, W, y),
                fill=(18 + int(18 * (1 - ratio)), 30 + int(24 * (1 - ratio)), 54 + int(36 * (1 - ratio)), 255),
            )
        canvas.alpha_composite(grad)
        return
    blurred = bg.filter(ImageFilter.GaussianBlur(data.get("bg_blur", 20) or 20))
    blurred = ImageEnhance.Brightness(blurred).enhance(0.72)
    canvas.alpha_composite(_cover(blurred))
    main = _cover(bg)
    main.putalpha(118)
    canvas.alpha_composite(main)
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil)
    for y in range(100):
        vd.line((0, y, W, y), fill=(4, 10, 20, int(95 * (1 - y / 100))))
    for y in range(150):
        vd.line((0, H - 150 + y, W, H - 150 + y), fill=(4, 10, 20, int(60 * (y / 150))))
    canvas.alpha_composite(veil)


def _draw_character(canvas: Image.Image, data: dict) -> None:
    char = _data_image(data.get("char_url", ""))
    if char is None:
        return
    height = max(80, int(data.get("char_height", 907) or 907))
    max_width = int(W * max(10, min(100, float(data.get("char_max_width", 62) or 62))) / 100)
    width = int(char.width * height / max(1, char.height))
    if width > max_width:
        width = max_width
        height = int(char.height * width / max(1, char.width))
    char = char.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)
    center_x = int(W * float(data.get("char_left", 31) or 31) / 100)
    top = int(data.get("char_top", 18) or 18)
    canvas.alpha_composite(char, (center_x - char.width // 2, top))


def _draw_scene_tag(canvas: Image.Image) -> None:
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(12)
    text = "GAL MODE"
    width = int(draw.textlength(text, font=font)) + 43
    draw.rounded_rectangle(
        (28, 24, 28 + width, 51),
        radius=14,
        fill=(8, 18, 32, 112),
        outline=(255, 255, 255, 56),
        width=1,
    )
    draw.ellipse((39, 33, 46, 40), fill=(103, 199, 255, 255))
    draw.text((53, 30), text, font=font, fill=(234, 244, 255, 255))
    canvas.alpha_composite(overlay)


def _draw_options(canvas: Image.Image, data: dict) -> None:
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    header_top = int(data.get("opt_header_top", 112) or 112)
    draw.rounded_rectangle(
        (OPT_LEFT, header_top, OPT_LEFT + OPT_W, header_top + 24),
        radius=9,
        fill=(8, 18, 32, 106),
        outline=(255, 255, 255, 40),
    )
    draw.text(
        (OPT_LEFT + 11, header_top + 5),
        "选择你的回应",
        font=_font(11),
        fill=(235, 245, 255, 235),
    )
    for item in data.get("options", []):
        top = int(item.get("top", 0) or 0)
        box = (OPT_LEFT, top, OPT_LEFT + OPT_W, top + OPT_H)
        free = bool(item.get("cls"))
        _shadow_round(
            draw,
            box,
            12,
            (245, 250, 255, 228) if free else (255, 255, 255, 246),
        )
        draw.rounded_rectangle(
            box,
            radius=12,
            outline=(43, 115, 216, 118) if free else (255, 255, 255, 246),
            width=2,
        )
        if free:
            _draw_dashed_rect(draw, box, (43, 115, 216, 120), width=1, dash=7)
            draw.rounded_rectangle(
                (OPT_LEFT, top, OPT_LEFT + 4, top + OPT_H),
                radius=2,
                fill=(185, 211, 236, 255),
            )
        else:
            draw.rounded_rectangle(
                (OPT_LEFT, top, OPT_LEFT + 4, top + OPT_H),
                radius=2,
                fill=_BLUE,
            )
        letter_font = _font(15)
        draw.text(
            (OPT_LEFT + 14, top + 15),
            str(item.get("letter", "")),
            font=letter_font,
            fill=(125, 153, 183, 255) if free else _BLUE,
        )
        text_font = _font(13 if free else 16)
        text = _truncate(draw, str(item.get("text", "")), text_font, OPT_W - 58)
        draw.text(
            (OPT_LEFT + 43, top + 16 if free else top + 14),
            text,
            font=text_font,
            fill=(126, 147, 169, 255) if free else (29, 51, 80, 255),
        )
    canvas.alpha_composite(overlay)


def _draw_dialog(canvas: Image.Image, data: dict) -> None:
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    box = (BOX_LEFT, BOX_TOP, BOX_LEFT + BOX_W, BOX_TOP + BOX_H)
    _shadow_round(draw, box, 18, (248, 251, 255, int(255 * float(data.get("box_alpha", 0.94) or 0.94))))
    draw.rounded_rectangle(box, radius=18, outline=(255, 255, 255, 242), width=2)
    # Small callout in the top-right, like the HTML card.
    draw.polygon(
        [(BOX_LEFT + BOX_W - 70, BOX_TOP), (BOX_LEFT + BOX_W - 50, BOX_TOP), (BOX_LEFT + BOX_W - 60, BOX_TOP - 10)],
        fill=(248, 251, 255, 242),
    )

    x = BOX_LEFT + 26
    # Player row
    avatar_y = BOX_TOP + 11
    draw.ellipse((x, avatar_y, x + 26, avatar_y + 26), fill=(103, 155, 214, 255), outline=(255, 255, 255, 255), width=2)
    draw.text((x + 7, avatar_y + 6), "玩", font=_font(11), fill=_WHITE)
    speaker = _truncate(draw, str(data.get("speaker", "某人")), _font(12), 120)
    draw.text((x + 36, avatar_y + 5), speaker, font=_font(12), fill=(74, 111, 158, 255))
    sep_x = x + 36 + int(draw.textlength(speaker, font=_font(12))) + 8
    draw.text((sep_x, avatar_y + 4), ">", font=_font(14), fill=(168, 189, 212, 255))
    quote = _truncate(draw, str(data.get("quote", "")), _font(16), BOX_W - 310)
    draw.text((sep_x + 18, avatar_y + 3), quote, font=_font(16), fill=(34, 69, 110, 255))

    # Divider
    divider_y = BOX_TOP + 42
    draw.line((x, divider_y, x + BOX_W - 52, divider_y), fill=(120, 165, 215, 104), width=1)

    lines = data.get("lines") or []
    if not lines:
        lines = [{"text": data.get("say", ""), "font": 22}]
    line_area_top = divider_y + 7
    line_area_bottom = BOX_TOP + BOX_H - 25
    total_height = sum(max(18, int(item.get("font", 20) or 20)) + 5 for item in lines)
    y = line_area_top + max(0, (line_area_bottom - line_area_top - total_height) // 2)
    first_name = _truncate(draw, str(data.get("bot_label", "小鲸鱼")), _font(11), 70)
    pill_w = int(draw.textlength(first_name, font=_font(11))) + 18
    for index, item in enumerate(lines):
        font_size = max(17, int(item.get("font", 20) or 20))
        line_y = y
        if index == 0:
            draw.rounded_rectangle(
                (x, line_y + 2, x + pill_w, line_y + 22),
                radius=6,
                fill=_BLUE,
            )
            draw.text((x + 9, line_y + 4), first_name, font=_font(11), fill=_WHITE)
        text_x = x + pill_w + 10
        text = _truncate(draw, str(item.get("text", "")), _font(font_size), x + BOX_W - 44 - text_x)
        draw.text((text_x, line_y), text, font=_font(font_size), fill=_INK)
        y += font_size + 5

    # Footer
    footer_y = BOX_TOP + BOX_H - 20
    draw.text(
        (x, footer_y),
        str(data.get("hint", "")).replace("✎", "").replace("✏", ""),
        font=_font(10),
        fill=(124, 147, 171, 255),
    )
    turn = str(data.get("turn_label", ""))
    if turn:
        draw.text(
            (BOX_LEFT + BOX_W - 210 - int(draw.textlength(turn, font=_font(10))), footer_y),
            turn,
            font=_font(10),
            fill=(107, 134, 163, 255),
        )

    # Six decorative control icons on the bottom-right, matching the HTML bar.
    icon_x = BOX_LEFT + BOX_W - 186
    for i in range(6):
        bx = icon_x + i * 32
        by = BOX_TOP + BOX_H - 34
        draw.rounded_rectangle((bx, by, bx + 26, by + 26), radius=8, fill=(48, 140, 220, 255))
        cx, cy = bx + 13, by + 13
        if i == 0:
            for row in range(3):
                draw.rectangle((bx + 7, by + 7 + row * 4, bx + 19, by + 8 + row * 4), fill=_WHITE)
        elif i == 1:
            draw.polygon([(bx + 9, by + 7), (bx + 19, by + 13), (bx + 9, by + 19)], fill=_WHITE)
        elif i == 2:
            draw.polygon([(bx + 6, by + 8), (bx + 13, by + 13), (bx + 6, by + 18)], fill=_WHITE)
            draw.polygon([(bx + 12, by + 8), (bx + 19, by + 13), (bx + 12, by + 18)], fill=_WHITE)
        elif i == 3:
            draw.rectangle((bx + 10, by + 6, bx + 15, by + 13), fill=_WHITE)
            draw.polygon([(bx + 7, by + 12), (bx + 18, by + 12), (bx + 12, by + 18)], fill=_WHITE)
            draw.rectangle((bx + 6, by + 19, bx + 20, by + 21), fill=_WHITE)
        elif i == 4:
            draw.rectangle((bx + 10, by + 12, bx + 15, by + 19), fill=_WHITE)
            draw.polygon([(bx + 7, by + 13), (bx + 18, by + 13), (bx + 12, by + 7)], fill=_WHITE)
            draw.rectangle((bx + 6, by + 19, bx + 20, by + 21), fill=_WHITE)
        else:
            draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), outline=_WHITE, width=2)
            for angle in range(0, 360, 45):
                px = cx + int(8 * math.cos(math.radians(angle)))
                py = cy + int(8 * math.sin(math.radians(angle)))
                draw.line((cx, cy, px, py), fill=_WHITE, width=2)
    canvas.alpha_composite(overlay)


def render_local(data: dict, config: PluginConfig | None = None) -> str:
    """Render one gal card to a JPEG and return its filesystem path."""
    canvas = Image.new("RGBA", (W, H), (10, 18, 32, 255))
    _draw_background(canvas, data)
    _draw_character(canvas, data)
    _draw_options(canvas, data)
    _draw_dialog(canvas, data)
    _draw_scene_tag(canvas)

    cache = plugin_data_dir("astrbot_plugin_gal_choice") / "image_cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"local_{int(time.time() * 1000)}.jpg"
    quality = config.int("image_quality", 90, 30, 100) if config else 90
    canvas.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)
    try:
        for old in sorted(cache.glob("local_*.jpg"), key=lambda p: p.stat().st_mtime)[:-30]:
            old.unlink()
    except OSError:
        pass
    return str(path)
