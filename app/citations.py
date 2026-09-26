"""Semantic Scholar citation enrichment."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

VERSION_SUFFIX = re.compile(r"v\d+$", re.IGNORECASE)
BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
FIELDS = "citationCount,influentialCitationCount,externalIds,title,year"


@dataclass
class CitationInfo:
    citation_count: int = 0
    influential_citation_count: int = 0


def strip_arxiv_version(arxiv_id: str) -> str:
    return VERSION_SUFFIX.sub("", arxiv_id.strip())


async def fetch_citations(
    arxiv_ids: list[str],
    timeout: float = 30.0,
    api_key: str = "",
) -> dict[str, CitationInfo]:
    """Return citation stats keyed by the original arxiv_id (with version if provided)."""
    if not arxiv_ids:
        return {}

    bare_to_originals: dict[str, list[str]] = {}
    for aid in arxiv_ids:
        bare = strip_arxiv_version(aid)
        bare_to_originals.setdefault(bare, []).append(aid)

    headers = {"User-Agent": "PaperPulse/1.0 (research-agent)"}
    if api_key.strip():
        headers["x-api-key"] = api_key.strip()

    results: dict[str, CitationInfo] = {}
    bare_ids = list(bare_to_originals.keys())

    # Semantic Scholar allows up to 500 ids per batch; keep chunks modest.
    chunk_size = 40
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for i in range(0, len(bare_ids), chunk_size):
            chunk = bare_ids[i : i + chunk_size]
            payload = {"ids": [f"ARXIV:{bare}" for bare in chunk]}
            try:
                response = await client.post(
                    f"{BATCH_URL}?fields={FIELDS}",
                    headers=headers,
                    json=payload,
                )
                if response.status_code == 429:
                    logger.warning("Semantic Scholar rate limited; continuing without citations for chunk")
                    continue
                response.raise_for_status()
                papers = response.json()
            except Exception:
                logger.exception("Semantic Scholar citation lookup failed for chunk starting at %s", i)
                continue

            if not isinstance(papers, list):
                continue

            for bare, paper in zip(chunk, papers):
                if not paper or not isinstance(paper, dict):
                    info = CitationInfo()
                else:
                    info = CitationInfo(
                        citation_count=int(paper.get("citationCount") or 0),
                        influential_citation_count=int(paper.get("influentialCitationCount") or 0),
                    )
                for original in bare_to_originals.get(bare, []):
                    results[original] = info

    return results
