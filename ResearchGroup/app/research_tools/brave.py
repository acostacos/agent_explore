"""Brave Search API client (news + web)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx

BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
VALID_FRESHNESS = {"pd", "pw", "pm", "py"}
MIN_INTERVAL_SECONDS = 1.1  # Brave free tier allows ~1 request/second

_lock = asyncio.Lock()
_last_call = 0.0


async def _throttle() -> None:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()


def _check(freshness: str, count: int) -> int:
    if freshness not in VALID_FRESHNESS:
        raise ValueError(f"freshness must be one of {sorted(VALID_FRESHNESS)}")
    return max(1, min(int(count), 20))


async def _get(
    url: str, api_key: str, params: dict[str, Any], client: Optional[httpx.AsyncClient]
) -> dict[str, Any]:
    await _throttle()
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await client.aclose()


async def news_search(
    query: str,
    api_key: str,
    freshness: str = "pw",
    count: int = 10,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    count = _check(freshness, count)
    data = await _get(BRAVE_NEWS_URL, api_key, {"q": query, "freshness": freshness, "count": count}, client)
    return [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "description": r.get("description"),
            "age": r.get("age"),
            "source": (r.get("meta_url") or {}).get("hostname"),
        }
        for r in data.get("results", [])
    ]


async def web_search(
    query: str,
    api_key: str,
    freshness: str = "pw",
    count: int = 10,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    count = _check(freshness, count)
    data = await _get(BRAVE_WEB_URL, api_key, {"q": query, "freshness": freshness, "count": count}, client)
    return [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "description": r.get("description"),
            "age": r.get("age"),
        }
        for r in (data.get("web") or {}).get("results", [])
    ]
