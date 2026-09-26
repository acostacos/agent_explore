"""Orchestrates a research run: fetch → enrich → rank → summarize → persist."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.arxiv_client import fetch_recent_papers
from app.citations import fetch_citations
from app.config import Settings, get_settings
from app.interests import list_keywords, sync_seed_keywords
from app.models import Paper, ResearchRun, SessionLocal, utcnow
from app.ranking import rank_papers
from app.summarizer import summarize_paper

logger = logging.getLogger(__name__)


class ResearchAgent:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def run(self, trigger: str = "scheduled", db: Session | None = None) -> ResearchRun:
        own_session = db is None
        session = db or SessionLocal()
        sync_seed_keywords(session, self.settings)
        keywords = list_keywords(session)

        run = ResearchRun(
            status="running",
            trigger=trigger,
            categories=",".join(self.settings.categories),
            keywords_used=", ".join(keywords),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        try:
            candidates = await fetch_recent_papers(
                categories=self.settings.categories,
                max_results=self.settings.papers_per_run,
                keywords=keywords,
            )

            citations = await fetch_citations(
                [p.arxiv_id for p in candidates],
                api_key=self.settings.semanticscholar_api_key,
            )
            ranked = rank_papers(
                candidates,
                keywords=keywords,
                citations=citations,
                require_keyword_match=bool(keywords) and self.settings.require_keyword_match,
            )

            existing_ids = set(session.scalars(select(Paper.arxiv_id)).all())

            added = 0
            for item in ranked:
                if item.paper.arxiv_id in existing_ids:
                    continue
                if added >= self.settings.papers_per_run:
                    break

                summary = await summarize_paper(item.paper, self.settings)
                record = Paper(
                    run_id=run.id,
                    arxiv_id=item.paper.arxiv_id,
                    title=item.paper.title,
                    authors=", ".join(item.paper.authors),
                    abstract=item.paper.abstract,
                    summary=summary,
                    categories=", ".join(item.paper.categories),
                    published_at=item.paper.published_at,
                    pdf_url=item.paper.pdf_url,
                    abs_url=item.paper.abs_url,
                    citation_count=item.citation_count,
                    influential_citation_count=item.influential_citation_count,
                    matched_keywords=", ".join(item.matched_keywords),
                    rank_score=item.rank_score,
                )
                session.add(record)
                existing_ids.add(item.paper.arxiv_id)
                added += 1

            run.papers_found = added
            run.status = "completed"
            run.finished_at = utcnow()
            session.commit()
            session.refresh(run)
            logger.info(
                "Research run %s completed with %s new papers (candidates=%s keywords=%s)",
                run.id,
                added,
                len(candidates),
                len(keywords),
            )
            return run
        except Exception as exc:
            logger.exception("Research run %s failed", run.id)
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = utcnow()
            session.commit()
            session.refresh(run)
            raise
        finally:
            if own_session:
                session.close()
