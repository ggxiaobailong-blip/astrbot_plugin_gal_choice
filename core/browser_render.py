# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional local Chromium renderer for the exact HTML/CSS card.

The Pillow renderer is dependency-free but cannot match CSS effects exactly.
When Playwright + Chromium is available this renderer screenshots the real
template locally, so the output matches the T2I design without any network.
"""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path

from jinja2 import Template

from .config import PluginConfig, plugin_data_dir

_LOCK = asyncio.Lock()
_PLAYWRIGHT = None
_BROWSER = None


class BrowserUnavailable(RuntimeError):
    pass


async def _get_browser():
    global _PLAYWRIGHT, _BROWSER
    if _BROWSER is not None:
        return _BROWSER
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - optional dependency
        raise BrowserUnavailable("未安装 playwright") from exc
    try:
        _PLAYWRIGHT = await async_playwright().start()
        _BROWSER = await _PLAYWRIGHT.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        return _BROWSER
    except Exception as exc:
        if _PLAYWRIGHT is not None:
            try:
                await _PLAYWRIGHT.stop()
            except Exception:
                pass
        _PLAYWRIGHT = None
        _BROWSER = None
        raise BrowserUnavailable(f"本地 Chromium 不可用: {exc}") from exc


async def close_browser() -> None:
    global _PLAYWRIGHT, _BROWSER
    browser, _BROWSER = _BROWSER, None
    playwright, _PLAYWRIGHT = _PLAYWRIGHT, None
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            await playwright.stop()
        except Exception:
            pass


async def render_browser(template: str, data: dict, config: PluginConfig | None = None) -> str:
    """Render the real Jinja template in local Chromium and return a JPEG path."""
    html = Template(template).render(**data)
    cache = plugin_data_dir("astrbot_plugin_gal_choice") / "image_cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"browser_{int(time.time() * 1000)}_{random.randint(1000, 9999)}.jpg"
    quality = config.int("image_quality", 90, 30, 100) if config else 90

    async with _LOCK:
        browser = await _get_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
        )
        try:
            page = await context.new_page()
            await page.set_content(html, wait_until="load")
            try:
                await page.evaluate("document.fonts.ready")
            except Exception:
                pass
            await page.screenshot(
                path=str(path),
                type="jpeg",
                quality=quality,
                full_page=False,
            )
        finally:
            await context.close()

    try:
        for old in sorted(cache.glob("browser_*.jpg"), key=lambda p: p.stat().st_mtime)[:-30]:
            old.unlink()
    except OSError:
        pass
    return str(path)
