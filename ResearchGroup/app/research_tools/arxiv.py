"""arXiv API client (https://info.arxiv.org/help/api/user-manual.html)."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import feedparser
import httpx

ARXIV_URL = "https://export.arxiv.org/api/query"
MIN_INTERVAL_SECONDS = 3.0  # arXiv asks for one request every 3 seconds
DEFAULT_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.MA"]
USER_AGENT = "agent-explore-research-tools/0.1 (weekly AI digest)"

_lock = asyncio.Lock()
_last_call = 0.0


async def _throttle() -> None:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()


def build_search_query(query: str, categories: list[str], start: datetime, end: datetime) -> str:
    """Build the arXiv ``search_query`` string: categories AND optional text AND submittedDate range."""
    cats = " OR ".join(f"cat:{c}" for c in categories)
    parts = [f"({cats})"]
    if query.strip():
        parts.append(f'all:"{query.strip()}"')
    fmt = "%Y%m%d%H%M"
    parts.append(f"submittedDate:[{start.strftime(fmt)} TO {end.strftime(fmt)}]")
    return " AND ".join(parts)


def parse_feed(text: str) -> list[dict[str, Any]]:
    feed = feedparser.parse(text)
    papers = []
    for e in feed.entries:
        pdf = next((link.href for link in e.get("links", []) if link.get("title") == "pdf"), None)
        papers.append(
            {
                "id": e.get("id"),
                "title": " ".join((e.get("title") or "").split()),
                "authors": [a.get("name") for a in e.get("authors", [])],
                "abstract": " ".join((e.get("summary") or "").split()),
                "published": e.get("published"),
                "link": e.get("link"),
                "pdf": pdf,
                "categories": [t.get("term") for t in e.get("tags", [])],
                "primary_category": (e.get("arxiv_primary_category") or {}).get("term"),
            }
        )
    return papers


async def search(
    query: str = "",
    categories: Optional[list[str]] = None,
    days_back: int = 7,
    max_results: int = 50,
    now: Optional[datetime] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    categories = categories or DEFAULT_CATEGORIES
    days_back = max(1, min(int(days_back), 60))
    max_results = max(1, min(int(max_results), 100))
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = end - timedelta(days=days_back)
    params = {
        "search_query": build_search_query(query, categories, start, end),
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    await _throttle()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        resp = await client.get(ARXIV_URL, params=params, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return parse_feed(resp.text)
    finally:
        if owns:
            await client.aclose()
