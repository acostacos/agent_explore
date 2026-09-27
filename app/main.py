"""FastAPI application — API + web UI for PaperPulse."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, col, select

from app.agent import ResearchAgent
from app.config import get_settings
from app.interests import list_keywords, parse_keywords, replace_keywords, sync_seed_keywords
from app.models import Paper, ResearchRun, configure_engine, get_db, init_db
from app.scheduler import next_run_time, shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path("data").mkdir(parents=True, exist_ok=True)
    configure_engine()
    init_db()
    sync_seed_keywords()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="PaperPulse", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class PaperUpdate(BaseModel):
    is_read: bool | None = None
    is_saved: bool | None = None


class InterestsUpdate(BaseModel):
    keywords: list[str] | str = Field(default_factory=list)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    runs = db.exec(
        select(ResearchRun)
        .options(selectinload(ResearchRun.papers))
        .order_by(col(ResearchRun.started_at).desc())
        .limit(12)
    ).all()
    latest_run = runs[0] if runs else None
    saved = db.exec(
        select(Paper)
        .where(Paper.is_saved == True)  # noqa: E712
        .order_by(col(Paper.rank_score).desc())
        .limit(20)
    ).all()
    unread_count = (
        db.exec(select(func.count()).select_from(Paper).where(Paper.is_read == False)).one()  # noqa: E712
        or 0
    )
    total_papers = db.exec(select(func.count()).select_from(Paper)).one() or 0
    keywords = list_keywords(db)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_name": settings.app_name,
            "runs": runs,
            "latest_run": latest_run,
            "saved": saved,
            "unread_count": unread_count,
            "total_papers": total_papers,
            "next_run": next_run_time(),
            "categories": settings.categories,
            "keywords": keywords,
            "llm_enabled": settings.llm_enabled,
            "telegram_enabled": settings.telegram_enabled,
            "schedule_day": settings.schedule_day_of_week,
            "schedule_hour": settings.schedule_hour,
            "schedule_minute": settings.schedule_minute,
        },
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    run = db.exec(
        select(ResearchRun)
        .options(selectinload(ResearchRun.papers))
        .where(ResearchRun.id == run_id)
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request,
        "run.html",
        {
            "app_name": settings.app_name,
            "run": run,
            "llm_enabled": settings.llm_enabled,
        },
    )


@app.get("/api/health")
async def health():
    settings = get_settings()
    return {
        "status": "ok",
        "next_run": next_run_time(),
        "telegram_enabled": settings.telegram_enabled,
        "strands": settings.llm_enabled,
    }


@app.get("/api/interests")
async def get_interests(db: Session = Depends(get_db)):
    return {"keywords": list_keywords(db)}


@app.put("/api/interests")
async def put_interests(body: InterestsUpdate, db: Session = Depends(get_db)):
    keywords = replace_keywords(db, parse_keywords(body.keywords), source="ui")
    return {"keywords": keywords}


@app.post("/interests")
async def interests_form(keywords: str = Form(""), db: Session = Depends(get_db)):
    replace_keywords(db, parse_keywords(keywords), source="ui")
    return RedirectResponse(url="/#interests", status_code=303)


@app.get("/api/runs")
async def list_runs(db: Session = Depends(get_db)):
    runs = db.exec(select(ResearchRun).order_by(col(ResearchRun.started_at).desc()).limit(50)).all()
    return [
        {
            "id": r.id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "status": r.status,
            "trigger": r.trigger,
            "papers_found": r.papers_found,
            "categories": r.categories,
            "keywords_used": r.keywords_used,
            "error_message": r.error_message,
        }
        for r in runs
    ]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.exec(
        select(ResearchRun)
        .options(selectinload(ResearchRun.papers))
        .where(ResearchRun.id == run_id)
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "status": run.status,
        "trigger": run.trigger,
        "papers_found": run.papers_found,
        "categories": run.categories,
        "keywords_used": run.keywords_used,
        "error_message": run.error_message,
        "papers": [_paper_dict(p) for p in run.papers],
    }


@app.get("/api/papers")
async def list_papers(
    saved: bool | None = None,
    unread: bool | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = select(Paper).order_by(col(Paper.rank_score).desc(), col(Paper.created_at).desc()).limit(
        min(limit, 200)
    )
    if saved is True:
        q = q.where(Paper.is_saved == True)  # noqa: E712
    if unread is True:
        q = q.where(Paper.is_read == False)  # noqa: E712
    papers = db.exec(q).all()
    return [_paper_dict(p) for p in papers]


@app.patch("/api/papers/{paper_id}")
async def update_paper(paper_id: int, body: PaperUpdate, db: Session = Depends(get_db)):
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if body.is_read is not None:
        paper.is_read = body.is_read
    if body.is_saved is not None:
        paper.is_saved = body.is_saved
    db.commit()
    db.refresh(paper)
    return _paper_dict(paper)


@app.post("/api/research/run")
async def trigger_research(db: Session = Depends(get_db)):
    """Manually kick off a Strands research run."""
    active = db.exec(select(ResearchRun).where(ResearchRun.status == "running")).first()
    if active:
        raise HTTPException(status_code=409, detail="A research run is already in progress")

    agent = ResearchAgent()
    try:
        run = await agent.run(trigger="manual", db=db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "id": run.id,
        "status": run.status,
        "papers_found": run.papers_found,
        "trigger": run.trigger,
        "keywords_used": run.keywords_used,
    }


@app.post("/research/run")
async def trigger_research_form(db: Session = Depends(get_db)):
    """Form POST that redirects back to the home page."""
    active = db.exec(select(ResearchRun).where(ResearchRun.status == "running")).first()
    if not active:
        agent = ResearchAgent()
        try:
            await agent.run(trigger="manual", db=db)
        except Exception:
            logger.exception("Manual research run failed")
    return RedirectResponse(url="/", status_code=303)


def _paper_dict(p: Paper) -> dict:
    return {
        "id": p.id,
        "run_id": p.run_id,
        "arxiv_id": p.arxiv_id,
        "title": p.title,
        "authors": p.authors,
        "abstract": p.abstract,
        "summary": p.summary,
        "categories": p.categories,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "pdf_url": p.pdf_url,
        "abs_url": p.abs_url,
        "is_read": p.is_read,
        "is_saved": p.is_saved,
        "citation_count": p.citation_count,
        "influential_citation_count": p.influential_citation_count,
        "matched_keywords": p.matched_keywords,
        "rank_score": p.rank_score,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
