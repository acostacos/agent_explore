"""Strands @tool wrappers for the PaperPulse research pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlmodel import select
from strands import tool

import app.models as models
from app.arxiv_client import ArxivPaper, fetch_recent_papers
from app.citations import CitationInfo, fetch_citations
from app.config import get_settings
from app.interests import list_keywords, sync_seed_keywords
from app.models import Paper, ResearchRun, utcnow
from app.ranking import rank_papers
from app.summarizer import summarize_paper
from app.telegram import notify_run_digest

logger = logging.getLogger(__name__)

# In-process scratch pad shared across tool calls for a single research run.
_RUN_STATE: dict[str, Any] = {}


def reset_run_state() -> None:
    _RUN_STATE.clear()


def get_run_state() -> dict[str, Any]:
    return _RUN_STATE


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # Called from within an event loop — use a fresh loop in a thread if needed.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _paper_to_dict(paper: ArxivPaper) -> dict:
    return {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "categories": paper.categories,
        "published_at": paper.published_at.isoformat() if paper.published_at else None,
        "pdf_url": paper.pdf_url,
        "abs_url": paper.abs_url,
    }


def _dict_to_paper(data: dict) -> ArxivPaper:
    from datetime import datetime

    published = data.get("published_at")
    published_at = datetime.fromisoformat(published) if published else None
    return ArxivPaper(
        arxiv_id=data["arxiv_id"],
        title=data["title"],
        authors=list(data.get("authors") or []),
        abstract=data.get("abstract") or "",
        categories=list(data.get("categories") or []),
        published_at=published_at,
        pdf_url=data.get("pdf_url") or "",
        abs_url=data.get("abs_url") or "",
    )


@tool
def load_interest_keywords() -> str:
    """Load interest keywords from the database (after syncing env/file seeds).

    Returns a JSON object with a keywords list used to bias arXiv search and ranking.
    """
    settings = get_settings()
    session = models.SessionLocal()
    try:
        sync_seed_keywords(session, settings)
        keywords = list_keywords(session)
        _RUN_STATE["keywords"] = keywords
        return json.dumps({"keywords": keywords, "count": len(keywords)})
    finally:
        session.close()


@tool
def start_research_run(trigger: str = "scheduled") -> str:
    """Create a running ResearchRun row in the database.

    Args:
        trigger: How the run was started — "scheduled" or "manual".
    """
    settings = get_settings()
    keywords = list(_RUN_STATE.get("keywords") or [])
    session = models.SessionLocal()
    try:
        run = ResearchRun(
            status="running",
            trigger=trigger,
            categories=",".join(settings.categories),
            keywords_used=", ".join(keywords),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        _RUN_STATE["run_id"] = run.id
        _RUN_STATE["trigger"] = trigger
        return json.dumps({"run_id": run.id, "status": run.status, "trigger": trigger})
    finally:
        session.close()


@tool
def fetch_arxiv_candidates() -> str:
    """Fetch recent arXiv candidate papers for configured AI categories and interests.

    Oversamples results so ranking can prioritize new, well-cited, on-topic papers.
    """
    settings = get_settings()
    keywords = list(_RUN_STATE.get("keywords") or [])
    papers = _run_async(
        fetch_recent_papers(
            categories=settings.categories,
            max_results=settings.papers_per_run,
            keywords=keywords,
        )
    )
    payload = [_paper_to_dict(p) for p in papers]
    _RUN_STATE["candidates"] = payload
    return json.dumps({"count": len(payload), "arxiv_ids": [p["arxiv_id"] for p in payload[:30]]})


@tool
def enrich_citations() -> str:
    """Look up Semantic Scholar citation counts for the fetched arXiv candidates."""
    settings = get_settings()
    candidates = list(_RUN_STATE.get("candidates") or [])
    ids = [c["arxiv_id"] for c in candidates]
    citations = _run_async(fetch_citations(ids, api_key=settings.semanticscholar_api_key))
    serializable = {
        aid: {
            "citation_count": info.citation_count,
            "influential_citation_count": info.influential_citation_count,
        }
        for aid, info in citations.items()
    }
    _RUN_STATE["citations"] = serializable
    cited = sum(1 for v in serializable.values() if v["citation_count"] > 0)
    return json.dumps({"looked_up": len(ids), "with_citations": cited})


@tool
def rank_and_select_papers() -> str:
    """Rank candidates by interest match, citation velocity, and recency; keep top N new papers."""
    settings = get_settings()
    keywords = list(_RUN_STATE.get("keywords") or [])
    candidates = [_dict_to_paper(c) for c in (_RUN_STATE.get("candidates") or [])]
    raw_cites = _RUN_STATE.get("citations") or {}
    citations = {
        aid: CitationInfo(
            citation_count=int(v.get("citation_count") or 0),
            influential_citation_count=int(v.get("influential_citation_count") or 0),
        )
        for aid, v in raw_cites.items()
    }
    ranked = rank_papers(
        candidates,
        keywords=keywords,
        citations=citations,
        require_keyword_match=bool(keywords) and settings.require_keyword_match,
    )

    session = models.SessionLocal()
    try:
        existing_ids = set(session.exec(select(Paper.arxiv_id)).all())
    finally:
        session.close()

    selected = []
    for item in ranked:
        if item.paper.arxiv_id in existing_ids:
            continue
        if len(selected) >= settings.papers_per_run:
            break
        selected.append(
            {
                **_paper_to_dict(item.paper),
                "citation_count": item.citation_count,
                "influential_citation_count": item.influential_citation_count,
                "matched_keywords": item.matched_keywords,
                "rank_score": item.rank_score,
            }
        )
    _RUN_STATE["selected"] = selected
    return json.dumps(
        {
            "selected": len(selected),
            "titles": [s["title"][:80] for s in selected[:10]],
        }
    )


@tool
def persist_summaries() -> str:
    """Summarize selected papers and persist them on the current research run."""
    settings = get_settings()
    run_id = _RUN_STATE.get("run_id")
    selected = list(_RUN_STATE.get("selected") or [])
    if not run_id:
        return json.dumps({"error": "no_run_id", "added": 0})

    session = models.SessionLocal()
    try:
        run = session.get(ResearchRun, run_id)
        if not run:
            return json.dumps({"error": "run_not_found", "added": 0})

        added = 0
        stored = []
        for item in selected:
            paper = _dict_to_paper(item)
            summary = _run_async(summarize_paper(paper, settings))
            record = Paper(
                run_id=run.id,
                arxiv_id=paper.arxiv_id,
                title=paper.title,
                authors=", ".join(paper.authors),
                abstract=paper.abstract,
                summary=summary,
                categories=", ".join(paper.categories),
                published_at=paper.published_at,
                pdf_url=paper.pdf_url,
                abs_url=paper.abs_url,
                citation_count=int(item.get("citation_count") or 0),
                influential_citation_count=int(item.get("influential_citation_count") or 0),
                matched_keywords=", ".join(item.get("matched_keywords") or []),
                rank_score=float(item.get("rank_score") or 0.0),
            )
            session.add(record)
            added += 1
            stored.append(
                {
                    "title": record.title,
                    "arxiv_id": record.arxiv_id,
                    "citation_count": record.citation_count,
                    "matched_keywords": record.matched_keywords,
                    "abs_url": record.abs_url,
                    "summary": summary,
                }
            )

        run.papers_found = added
        run.status = "completed"
        run.finished_at = utcnow()
        session.commit()
        session.refresh(run)
        _RUN_STATE["stored_papers"] = stored
        _RUN_STATE["status"] = "completed"
        return json.dumps({"run_id": run.id, "added": added, "status": "completed"})
    except Exception as exc:
        logger.exception("persist_summaries failed")
        run = session.get(ResearchRun, run_id) if run_id else None
        if run:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = utcnow()
            session.commit()
        _RUN_STATE["status"] = "failed"
        _RUN_STATE["error"] = str(exc)
        return json.dumps({"error": str(exc), "added": 0, "status": "failed"})
    finally:
        session.close()


@tool
def send_telegram_digest() -> str:
    """Send a Telegram message summarizing the completed research run.

    Skips quietly when TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured.
    """
    run_id = _RUN_STATE.get("run_id")
    status = _RUN_STATE.get("status") or "completed"
    trigger = _RUN_STATE.get("trigger") or "scheduled"
    keywords = ", ".join(_RUN_STATE.get("keywords") or [])
    papers = list(_RUN_STATE.get("stored_papers") or [])
    if not run_id:
        return json.dumps({"ok": False, "error": "no_run_id"})
    result = notify_run_digest(
        run_id=int(run_id),
        status=status,
        trigger=trigger,
        keywords=keywords,
        papers=papers,
    )
    return json.dumps(result)
