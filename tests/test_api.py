import app.models as models
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.scheduler import shutdown_scheduler


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
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
    assert res.json()["status"] == "ok"


def test_home_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"PaperPulse" in res.content


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
