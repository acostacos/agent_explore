"""Tests for Strands research entrypoint (mocked LLM path)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import app.models as models
from app.config import get_settings
from app.strands_agent import run_pipeline_deterministic, run_research


def test_run_research_uses_deterministic_without_openai(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    interests = tmp_path / "i.txt"
    interests.write_text("llm agents\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("INTERESTS_FILE", str(interests))
    monkeypatch.setenv("INTEREST_KEYWORDS", "")
    monkeypatch.setenv("PAPERS_PER_RUN", "2")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    models.configure_engine(f"sqlite:///{db_path}")
    models.init_db()

    fake_papers = [
        {
            "arxiv_id": "2401.00001v1",
            "title": "LLM Agents for Science",
            "authors": ["A"],
            "abstract": "We propose LLM agents for scientific workflows.",
            "categories": ["cs.AI"],
            "published_at": "2026-09-20T00:00:00+00:00",
            "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
            "abs_url": "https://arxiv.org/abs/2401.00001",
        },
        {
            "arxiv_id": "2401.00002v1",
            "title": "Other Paper",
            "authors": ["B"],
            "abstract": "Unrelated abstract about cats.",
            "categories": ["cs.LG"],
            "published_at": "2026-09-21T00:00:00+00:00",
            "pdf_url": "https://arxiv.org/pdf/2401.00002.pdf",
            "abs_url": "https://arxiv.org/abs/2401.00002",
        },
    ]

    async def fake_fetch(**kwargs):
        from app.tools.research_tools import _dict_to_paper

        return [_dict_to_paper(p) for p in fake_papers]

    async def fake_cites(ids, api_key=""):
        from app.citations import CitationInfo

        return {i: CitationInfo(citation_count=5, influential_citation_count=1) for i in ids}

    with (
        patch("app.tools.research_tools.fetch_recent_papers", side_effect=fake_fetch),
        patch("app.tools.research_tools.fetch_citations", side_effect=fake_cites),
        patch("app.telegram.send_message", return_value={"ok": False, "skipped": True}),
    ):
        result = run_research(trigger="manual")

    assert result["status"] == "completed"
    assert result["papers_found"] == 2
    assert result["run_id"]


def test_run_research_with_strands_invokes_agent(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("INTERESTS_FILE", str(tmp_path / "missing.txt"))
    get_settings.cache_clear()
    models.configure_engine(f"sqlite:///{db_path}")
    models.init_db()

    fake_agent = MagicMock()
    fake_agent.return_value = "done"

    def fake_pipeline(trigger="scheduled"):
        return {
            "run_id": 1,
            "status": "completed",
            "papers_found": 0,
            "trigger": trigger,
            "keywords_used": "",
        }

    with (
        patch("app.strands_agent.build_agent", return_value=fake_agent),
        patch("app.strands_agent.run_pipeline_deterministic", side_effect=fake_pipeline),
        patch("app.strands_agent.reset_run_state"),
        patch(
            "app.strands_agent.get_run_state",
            return_value={
                "run_id": 99,
                "status": "completed",
                "stored_papers": [],
                "keywords": ["rag"],
                "trigger": "scheduled",
            },
        ),
    ):
        from app.strands_agent import run_research_with_strands

        result = run_research_with_strands(trigger="scheduled")

    fake_agent.assert_called_once()
    assert result["run_id"] == 99
    assert result["status"] == "completed"
