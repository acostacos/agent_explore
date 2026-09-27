"""Strands Agents entrypoint for PaperPulse research runs."""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent
from strands.models.openai import OpenAIModel

from app.config import Settings, get_settings
from app.models import ResearchRun
from app.tools.research_tools import (
    enrich_citations,
    fetch_arxiv_candidates,
    get_run_state,
    load_interest_keywords,
    persist_summaries,
    rank_and_select_papers,
    reset_run_state,
    send_telegram_digest,
    start_research_run,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are PaperPulse, a research agent that builds a weekly AI paper digest.

Always follow this exact tool workflow in order, without skipping steps:
1. load_interest_keywords
2. start_research_run (pass the trigger you were given)
3. fetch_arxiv_candidates
4. enrich_citations
5. rank_and_select_papers
6. persist_summaries
7. send_telegram_digest

After the tools finish, reply with a one-sentence status including run id and papers added.
Do not invent papers. Prefer tool results over your own knowledge.
"""

TOOLS = [
    load_interest_keywords,
    start_research_run,
    fetch_arxiv_candidates,
    enrich_citations,
    rank_and_select_papers,
    persist_summaries,
    send_telegram_digest,
]


def build_agent(settings: Settings | None = None) -> Agent:
    settings = settings or get_settings()
    if not settings.openai_api_key.strip():
        raise RuntimeError(
            "OPENAI_API_KEY is required to run the Strands research agent. "
            "Set it in your environment or .env file."
        )
    model = OpenAIModel(
        client_args={"api_key": settings.openai_api_key},
        model_id=settings.openai_model,
        params={"temperature": 0.2, "max_tokens": 1024},
    )
    return Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=TOOLS)


def run_pipeline_deterministic(trigger: str = "scheduled") -> dict[str, Any]:
    """Execute the tool chain in fixed order without an LLM (tests / offline)."""
    reset_run_state()
    load_interest_keywords()
    start_research_run(trigger=trigger)
    fetch_arxiv_candidates()
    enrich_citations()
    rank_and_select_papers()
    persist_summaries()
    send_telegram_digest()
    state = get_run_state()
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "papers_found": len(state.get("stored_papers") or []),
        "trigger": trigger,
        "keywords_used": ", ".join(state.get("keywords") or []),
        "error": state.get("error"),
    }


def run_research_with_strands(trigger: str = "scheduled", settings: Settings | None = None) -> dict[str, Any]:
    """Invoke the Strands agent to orchestrate a full research run."""
    settings = settings or get_settings()
    reset_run_state()
    agent = build_agent(settings)
    prompt = (
        f"Run the weekly AI paper research digest now. trigger={trigger}. "
        "Call every tool in the required order, then stop."
    )
    try:
        agent(prompt)
    except Exception:
        logger.exception("Strands agent invocation failed")
        state = get_run_state()
        run_id = state.get("run_id")
        if run_id and state.get("status") != "completed":
            # Best-effort: mark failed if tools did not finish.
            session = __import__("app.models", fromlist=["SessionLocal"]).SessionLocal()
            try:
                run = session.get(ResearchRun, run_id)
                if run and run.status == "running":
                    from app.models import utcnow

                    run.status = "failed"
                    run.error_message = "Strands agent stopped before persist_summaries completed"
                    run.finished_at = utcnow()
                    session.commit()
            finally:
                session.close()
        raise

    state = get_run_state()
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status") or "completed",
        "papers_found": len(state.get("stored_papers") or []),
        "trigger": trigger,
        "keywords_used": ", ".join(state.get("keywords") or []),
        "error": state.get("error"),
    }


def run_research(trigger: str = "scheduled", settings: Settings | None = None) -> dict[str, Any]:
    """Public entrypoint: Strands when OpenAI is configured, else deterministic tool chain."""
    settings = settings or get_settings()
    if settings.llm_enabled:
        return run_research_with_strands(trigger=trigger, settings=settings)
    logger.warning("OPENAI_API_KEY missing — running deterministic Strands tool pipeline")
    return run_pipeline_deterministic(trigger=trigger)
