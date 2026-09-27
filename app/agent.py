"""Research agent facade — delegates to the Strands Agents pipeline."""

from __future__ import annotations

import logging

from sqlmodel import Session

from app.config import Settings, get_settings
from app.models import ResearchRun
from app.strands_agent import run_research

logger = logging.getLogger(__name__)


class ResearchAgent:
    """Thin wrapper kept for scheduler/API compatibility."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def run(self, trigger: str = "scheduled", db: Session | None = None) -> ResearchRun:
        # db is accepted for API compatibility; tools open their own sessions.
        _ = db
        result = run_research(trigger=trigger, settings=self.settings)
        run_id = result.get("run_id")
        if not run_id:
            raise RuntimeError(result.get("error") or "Research run did not create a run id")

        import app.models as models

        session = models.SessionLocal()
        try:
            run = session.get(ResearchRun, run_id)
            if not run:
                raise RuntimeError(f"Research run {run_id} not found after agent finished")
            # Detach attributes we need after close.
            session.expunge(run)
            return run
        finally:
            session.close()
