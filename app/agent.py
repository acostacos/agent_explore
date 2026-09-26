"""Orchestrates a research run: fetch → summarize → persist."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.arxiv_client import fetch_recent_papers
from app.config import Settings, get_settings
from app.models import Paper, ResearchRun, SessionLocal, utcnow
from app.summarizer import summarize_paper

logger = logging.getLogger(__name__)


class ResearchAgent:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def run(self, trigger: str = "scheduled", db: Session | None = None) -> ResearchRun:
        own_session = db is None
        session = db or SessionLocal()
        run = ResearchRun(
            status="running",
            trigger=trigger,
            categories=",".join(self.settings.categories),
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        try:
            papers = await fetch_recent_papers(
                categories=self.settings.categories,
                max_results=self.settings.papers_per_run,
            )

            # Skip papers we already stored (by arxiv_id).
            existing_ids = set(
                session.scalars(select(Paper.arxiv_id)).all()
            )

            added = 0
            for item in papers:
                if item.arxiv_id in existing_ids:
                    continue

                summary = await summarize_paper(item, self.settings)
                record = Paper(
                    run_id=run.id,
                    arxiv_id=item.arxiv_id,
                    title=item.title,
                    authors=", ".join(item.authors),
                    abstract=item.abstract,
                    summary=summary,
                    categories=", ".join(item.categories),
                    published_at=item.published_at,
                    pdf_url=item.pdf_url,
                    abs_url=item.abs_url,
                )
                session.add(record)
                existing_ids.add(item.arxiv_id)
                added += 1

            run.papers_found = added
            run.status = "completed"
            run.finished_at = utcnow()
            session.commit()
            session.refresh(run)
            logger.info("Research run %s completed with %s new papers", run.id, added)
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
