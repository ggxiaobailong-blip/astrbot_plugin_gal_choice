# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reliable image rendering helper for the GalGame card."""

from __future__ import annotations

import asyncio
import re
import time

from .config import PluginConfig

try:
    from .local_render import render_local
except Exception:  # pragma: no cover - Pillow missing on a stripped host
    render_local = None

try:
    from .browser_render import render_browser
except Exception:  # pragma: no cover - optional dependency
    render_browser = None

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("astrbot.plugin.gal_choice.render")

# Avoid hammering an endpoint that just returned 502/503.
_BAD_UNTIL: dict[str, float] = {}
_ENDPOINT_SPLIT = re.compile(r"[,;\s]+")


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = str(value or "").strip().rstrip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _endpoint_candidates(plugin, config: PluginConfig) -> list[str]:
    preferred = config.str("render_endpoint", "").strip()
    preferred_list = _ENDPOINT_SPLIT.split(preferred) if preferred else []
    renderer = getattr(getattr(plugin, "context", None), "html_renderer", None)
    network = getattr(renderer, "network_strategy", None)
    pool = list(getattr(network, "endpoints", None) or [])
    base = getattr(network, "BASE_RENDER_URL", None)
    if base:
        pool.append(base)
    return _dedupe([*preferred_list, *pool])


async def _render_one(
    renderer,
    endpoint: str,
    template: str,
    data: dict,
    options: dict,
    timeout: float,
) -> str:
    return await asyncio.wait_for(
        renderer.render_custom_template(
            template,
            data,
            return_url=True,
            options=options,
            endpoint=endpoint,
        ),
        timeout=timeout,
    )


async def render_image(
    plugin,
    config: PluginConfig,
    template: str,
    data: dict,
    options: dict,
    timeout: int = 90,
) -> str:
    """Render with the configured backend, falling back to remote T2I."""
    backend = config.str("render_backend", "auto").strip().lower()
    if backend in {"auto", "browser"} and render_browser is not None:
        try:
            browser_path = await render_browser(template, data, config)
            if browser_path:
                return browser_path
        except Exception as exc:
            logger.warning("[gal] 本地浏览器出图不可用，改用 Pillow: %s", exc)

    if backend in {"auto", "local", "browser"} and render_local is not None:
        try:
            local_path = await asyncio.to_thread(render_local, data, config)
            if local_path:
                return local_path
        except Exception as exc:
            logger.warning("[gal] 本地出图失败，回退远程 T2I: %s", exc)

    renderer = getattr(getattr(plugin, "context", None), "html_renderer", None)
    candidates = _endpoint_candidates(plugin, config)
    if renderer is None or not hasattr(renderer, "render_custom_template"):
        return await asyncio.wait_for(
            plugin.html_render(template, data, options=options),
            timeout=timeout,
        )
    if not candidates:
        return await asyncio.wait_for(
            plugin.html_render(template, data, options=options),
            timeout=timeout,
        )

    deadline = time.monotonic() + max(30, timeout)
    errors: list[str] = []
    for round_no in range(2):
        tried_any = False
        now = time.monotonic()
        for endpoint in candidates:
            if time.monotonic() >= deadline:
                break
            if _BAD_UNTIL.get(endpoint, 0) > now:
                continue
            tried_any = True
            remaining = max(8.0, min(30.0, deadline - time.monotonic()))
            try:
                result = await _render_one(
                    renderer,
                    endpoint,
                    template,
                    data,
                    options,
                    remaining,
                )
                _BAD_UNTIL.pop(endpoint, None)
                return result
            except asyncio.TimeoutError:
                errors.append(f"{endpoint}: 超时")
                _BAD_UNTIL[endpoint] = time.monotonic() + 20
                logger.warning("[gal] 文转图端点超时: %s", endpoint)
            except Exception as exc:
                status = str(exc)
                errors.append(f"{endpoint}: {status or type(exc).__name__}")
                if "502" in status or "503" in status:
                    _BAD_UNTIL[endpoint] = time.monotonic() + 2
                logger.warning("[gal] 文转图端点失败 %s: %s", endpoint, exc)
        if time.monotonic() >= deadline:
            break
        if not tried_any and round_no == 0:
            # Every endpoint is cooling down; wait one short interval.
            await asyncio.sleep(2.2)
        elif round_no == 0:
            await asyncio.sleep(2.2)

    detail = "; ".join(errors[-4:]) if errors else "没有可用的文转图端点"
    raise RuntimeError(f"所有文转图端点都失败: {detail}")
