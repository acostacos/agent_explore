from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Text, event, text
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchRun(SQLModel, table=True):
    __tablename__ = "research_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = Field(default=None)
    status: str = Field(default="running", max_length=32)
    trigger: str = Field(default="scheduled", max_length=32)
    papers_found: int = Field(default=0)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    categories: str = Field(default="", max_length=255)
    keywords_used: str = Field(default="", sa_column=Column(Text, default=""))

    papers: list["Paper"] = Relationship(
        back_populates="run",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "Paper.rank_score.desc()",
        },
    )


class Paper(SQLModel, table=True):
    __tablename__ = "papers"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="research_runs.id", index=True)
    arxiv_id: str = Field(max_length=64, index=True)
    title: str = Field(max_length=512)
    authors: str = Field(default="", sa_column=Column(Text, default=""))
    abstract: str = Field(default="", sa_column=Column(Text, default=""))
    summary: str = Field(default="", sa_column=Column(Text, default=""))
    categories: str = Field(default="", max_length=255)
    published_at: Optional[datetime] = Field(default=None)
    pdf_url: str = Field(default="", max_length=512)
    abs_url: str = Field(default="", max_length=512)
    is_read: bool = Field(default=False)
    is_saved: bool = Field(default=False)
    citation_count: int = Field(default=0)
    influential_citation_count: int = Field(default=0)
    matched_keywords: str = Field(default="", max_length=512)
    rank_score: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=utcnow)

    run: Optional[ResearchRun] = Relationship(back_populates="papers")


class InterestKeyword(SQLModel, table=True):
    __tablename__ = "interest_keywords"

    id: Optional[int] = Field(default=None, primary_key=True)
    keyword: str = Field(max_length=255, unique=True, index=True)
    source: str = Field(default="ui", max_length=64)
    created_at: datetime = Field(default_factory=utcnow)


engine = None
SessionLocal = None


def configure_engine(database_url: str | None = None):
    """(Re)bind the SQLModel/SQLAlchemy engine — used at startup and in tests."""
    global engine, SessionLocal
    settings = get_settings()
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)

    def _session_factory():
        return Session(engine)

    SessionLocal = _session_factory

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


configure_engine()


def _sqlite_add_column_if_missing(table: str, column: str, ddl_type: str) -> None:
    assert engine is not None
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {row[1] for row in rows}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
            conn.commit()


def migrate_schema() -> None:
    """Best-effort additive migrations for existing SQLite databases."""
    settings = get_settings()
    if not settings.database_url.startswith("sqlite") or engine is None:
        return
    _sqlite_add_column_if_missing("research_runs", "keywords_used", "TEXT DEFAULT ''")
    _sqlite_add_column_if_missing("papers", "citation_count", "INTEGER DEFAULT 0")
    _sqlite_add_column_if_missing("papers", "influential_citation_count", "INTEGER DEFAULT 0")
    _sqlite_add_column_if_missing("papers", "matched_keywords", "VARCHAR(512) DEFAULT ''")
    _sqlite_add_column_if_missing("papers", "rank_score", "FLOAT DEFAULT 0")


def init_db() -> None:
    if engine is None:
        configure_engine()
    SQLModel.metadata.create_all(engine)
    migrate_schema()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Alias used by plan / newer call sites
get_session = get_db
