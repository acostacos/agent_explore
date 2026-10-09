"""FastMCP server exposing Brave Search and arXiv tools.

Follows the AgentCore MCP runtime contract: stateless streamable HTTP on 0.0.0.0:8000/mcp.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mcp.server.fastmcp import Context, FastMCP

import arxiv
import brave
from credentials import get_brave_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("research_tools")

mcp = FastMCP("research-tools", host="0.0.0.0", port=8000, stateless_http=True)  # nosec B104


def _headers(ctx: Optional[Context]) -> dict[str, str]:
    """Best-effort extraction of HTTP request headers from the MCP request context."""
    try:
        request = ctx.request_context.request  # type: ignore[union-attr]
        return dict(request.headers) if request is not None else {}
    except Exception:  # noqa: BLE001
        return {}


@mcp.tool()
async def brave_news_search(
    query: str, freshness: str = "pw", count: int = 10, ctx: Context = None  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    """Search recent news with the Brave Search API.

    Args:
        query: Search query, e.g. "large language model release".
        freshness: Recency filter: pd (24h), pw (7 days), pm (31 days), py (year).
        count: Number of results (1-20).
    """
    key = await get_brave_api_key(_headers(ctx))
    return await brave.news_search(query, key, freshness, count)


@mcp.tool()
async def brave_web_search(
    query: str, freshness: str = "pw", count: int = 10, ctx: Context = None  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    """Search the web with the Brave Search API.

    Args:
        query: Search query.
        freshness: Recency filter: pd (24h), pw (7 days), pm (31 days), py (year).
        count: Number of results (1-20).
    """
    key = await get_brave_api_key(_headers(ctx))
    return await brave.web_search(query, key, freshness, count)


@mcp.tool()
async def arxiv_search(
    query: str = "",
    categories: Optional[list[str]] = None,
    days_back: int = 7,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Search recent arXiv papers, newest first.

    Args:
        query: Optional keywords matched against all fields. Leave empty to list all recent papers.
        categories: arXiv categories, default ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.MA"].
        days_back: Only papers submitted in the last N days (1-60).
        max_results: Maximum number of papers (1-100).
    """
    return await arxiv.search(query, categories, days_back, max_results)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
