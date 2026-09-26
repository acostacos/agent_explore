"""Interest keyword loading from env, file, and database."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models as models
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_SPLIT = re.compile(r"[\n,;]+")


def normalize_keyword(raw: str) -> str:
    return " ".join(raw.strip().lower().split())


def parse_keywords(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        parts = raw
    else:
        parts = _SPLIT.split(raw)
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        kw = normalize_keyword(cleaned)
        if not kw or kw in seen:
            continue
        seen.add(kw)
        out.append(kw)
    return out


def load_keywords_from_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read interests file %s: %s", path, exc)
        return []
    return parse_keywords(text)


def sync_seed_keywords(db: Session | None = None, settings: Settings | None = None) -> list[str]:
    """Merge env + interests file into the DB without wiping UI-added keywords."""
    settings = settings or get_settings()
    own = db is None
    session = db or models.SessionLocal()
    try:
        seeded: list[tuple[str, str]] = []
        for kw in parse_keywords(settings.interest_keywords):
            seeded.append((kw, "env"))
        for kw in load_keywords_from_file(Path(settings.interests_file)):
            seeded.append((kw, "file"))

        existing = {
            normalize_keyword(row.keyword): row
            for row in session.scalars(select(models.InterestKeyword)).all()
        }
        for kw, source in seeded:
            if kw in existing:
                continue
            session.add(models.InterestKeyword(keyword=kw, source=source))
            existing[kw] = None  # type: ignore[assignment]
        session.commit()
        return list_keywords(session)
    finally:
        if own:
            session.close()


def list_keywords(db: Session) -> list[str]:
    rows = db.scalars(select(models.InterestKeyword).order_by(models.InterestKeyword.keyword)).all()
    return [r.keyword for r in rows]


def replace_keywords(db: Session, keywords: list[str], source: str = "ui") -> list[str]:
    """Replace the full interest set (used by the UI load form)."""
    normalized = parse_keywords(keywords)
    existing = db.scalars(select(models.InterestKeyword)).all()
    for row in existing:
        db.delete(row)
    db.flush()
    for kw in normalized:
        db.add(models.InterestKeyword(keyword=kw, source=source))
    db.commit()
    return list_keywords(db)


def add_keywords(db: Session, keywords: list[str], source: str = "ui") -> list[str]:
    normalized = parse_keywords(keywords)
    existing = {
        normalize_keyword(r.keyword) for r in db.scalars(select(models.InterestKeyword)).all()
    }
    for kw in normalized:
        if kw in existing:
            continue
        db.add(models.InterestKeyword(keyword=kw, source=source))
        existing.add(kw)
    db.commit()
    return list_keywords(db)
