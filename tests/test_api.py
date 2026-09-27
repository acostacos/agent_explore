import app.models as models
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.scheduler import shutdown_scheduler


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    interests = tmp_path / "interests.txt"
    interests.write_text("graph neural networks\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("INTERESTS_FILE", str(interests))
    monkeypatch.setenv("INTEREST_KEYWORDS", "causal inference")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    get_settings.cache_clear()
    models.configure_engine(f"sqlite:///{db_path}")
    models.init_db()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    shutdown_scheduler()
    get_settings.cache_clear()


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "telegram_enabled" in body
    assert "strands" in body


def test_home_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"PaperPulse" in res.content
    assert b"Interest keywords" in res.content
    assert b"Strands" in res.content


def test_interests_seeded_and_replaceable(client):
    res = client.get("/api/interests")
    assert res.status_code == 200
    seeded = set(res.json()["keywords"])
    assert "graph neural networks" in seeded
    assert "causal inference" in seeded

    res = client.put(
        "/api/interests",
        json={"keywords": ["LLM agents", "diffusion models", "LLM agents"]},
    )
    assert res.status_code == 200
    assert res.json()["keywords"] == ["diffusion models", "llm agents"]

    res = client.post(
        "/interests",
        data={"keywords": "multimodal, world models"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert client.get("/api/interests").json()["keywords"] == ["multimodal", "world models"]


def test_paper_update_roundtrip(client):
    db = models.SessionLocal()
    run = models.ResearchRun(status="completed", trigger="manual", papers_found=1)
    db.add(run)
    db.commit()
    db.refresh(run)
    paper = models.Paper(
        run_id=run.id,
        arxiv_id="2401.00001",
        title="Test Paper",
        authors="A Author",
        abstract="An abstract.",
        summary="A summary.",
        categories="cs.AI",
        abs_url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001.pdf",
        citation_count=12,
        rank_score=4.2,
        matched_keywords="llm agents",
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    paper_id = paper.id
    db.close()

    res = client.patch(f"/api/papers/{paper_id}", json={"is_read": True, "is_saved": True})
    assert res.status_code == 200
    body = res.json()
    assert body["is_read"] is True
    assert body["is_saved"] is True
    assert body["citation_count"] == 12
