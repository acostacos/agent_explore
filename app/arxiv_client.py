"""Fetch recent AI research papers from arXiv."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


@dataclass
class ArxivPaper:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published_at: datetime | None
    pdf_url: str
    abs_url: str


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def _parse_published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value) if "," in value else datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _entry_to_paper(entry: ET.Element) -> ArxivPaper | None:
    id_url = _text(entry.find("atom:id", ATOM_NS))
    if not id_url:
        return None
    arxiv_id = id_url.rsplit("/", 1)[-1]

    title = _text(entry.find("atom:title", ATOM_NS))
    abstract = _text(entry.find("atom:summary", ATOM_NS))
    authors = [_text(a.find("atom:name", ATOM_NS)) for a in entry.findall("atom:author", ATOM_NS)]
    authors = [a for a in authors if a]

    categories = [
        c.attrib.get("term", "")
        for c in entry.findall("atom:category", ATOM_NS)
        if c.attrib.get("term")
    ]

    published = _parse_published(_text(entry.find("atom:published", ATOM_NS)))

    pdf_url = ""
    abs_url = id_url
    for link in entry.findall("atom:link", ATOM_NS):
        rel = link.attrib.get("rel", "")
        href = link.attrib.get("href", "")
        title_attr = link.attrib.get("title", "")
        if title_attr == "pdf" or (rel == "related" and link.attrib.get("type") == "application/pdf"):
            pdf_url = href
        if rel == "alternate":
            abs_url = href

    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        categories=categories,
        published_at=published,
        pdf_url=pdf_url,
        abs_url=abs_url,
    )


def _quote_term(term: str) -> str:
    term = term.strip()
    if " " in term:
        return f'"{term}"'
    return term


def build_search_query(categories: list[str], keywords: list[str] | None = None) -> str:
    cat_parts = [f"cat:{cat}" for cat in categories]
    cat_clause = " OR ".join(cat_parts)
    if len(cat_parts) > 1:
        cat_clause = f"({cat_clause})"

    keywords = keywords or []
    if not keywords:
        return cat_clause

    kw_parts = [f"all:{_quote_term(kw)}" for kw in keywords]
    kw_clause = " OR ".join(kw_parts)
    if len(kw_parts) > 1:
        kw_clause = f"({kw_clause})"
    return f"{cat_clause} AND {kw_clause}"


async def _query_arxiv(query: str, max_results: int, timeout: float) -> list[ArxivPaper]:
    import asyncio

    url = (
        "https://export.arxiv.org/api/query"
        f"?search_query={quote_plus(query)}"
        f"&start=0&max_results={max_results}"
        "&sortBy=submittedDate&sortOrder=descending"
    )

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(4):
            response = await client.get(
                url, headers={"User-Agent": "PaperPulse/1.0 (research-agent)"}
            )
            if response.status_code == 429:
                last_error = httpx.HTTPStatusError(
                    "arXiv rate limited",
                    request=response.request,
                    response=response,
                )
                await asyncio.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            break
        else:
            assert last_error is not None
            raise last_error

    root = ET.fromstring(response.text)
    papers: list[ArxivPaper] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        paper = _entry_to_paper(entry)
        if paper and paper.title:
            papers.append(paper)
    return papers


async def fetch_recent_papers(
    categories: list[str],
    max_results: int = 20,
    keywords: list[str] | None = None,
    timeout: float = 30.0,
) -> list[ArxivPaper]:
    """Fetch candidate papers, optionally biased toward interest keywords."""
    keywords = keywords or []
    # Oversample so ranking can pick the best cited / most relevant subset.
    pool_size = max(max_results * 3, max_results)

    seen: dict[str, ArxivPaper] = {}

    if keywords:
        interest_query = build_search_query(categories, keywords)
        for paper in await _query_arxiv(interest_query, pool_size, timeout):
            seen[paper.arxiv_id] = paper

    # Always include a recent category sweep so brand-new work is not missed
    # when citations have not landed yet.
    recent_query = build_search_query(categories)
    for paper in await _query_arxiv(recent_query, pool_size, timeout):
        seen.setdefault(paper.arxiv_id, paper)

    return list(seen.values())
