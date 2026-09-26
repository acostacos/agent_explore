from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    trigger: Mapped[str] = mapped_column(String(32), default="scheduled")
    papers_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    categories: Mapped[str] = mapped_column(String(255), default="")
    keywords_used: Mapped[str] = mapped_column(Text, default="")

    papers: Mapped[list["Paper"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="Paper.rank_score.desc()",
    )


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("research_runs.id"), index=True)
    arxiv_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    authors: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    categories: Mapped[str] = mapped_column(String(255), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pdf_url: Mapped[str] = mapped_column(String(512), default="")
    abs_url: Mapped[str] = mapped_column(String(512), default="")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    influential_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_keywords: Mapped[str] = mapped_column(String(512), default="")
    rank_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped["ResearchRun"] = relationship(back_populates="papers")


class InterestKeyword(Base):
    __tablename__ = "interest_keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="ui")  # ui | file | env
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


engine = None
SessionLocal = None


def configure_engine(database_url: str | None = None):
    """(Re)bind the SQLAlchemy engine — used at startup and in tests."""
    global engine, SessionLocal
    settings = get_settings()
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

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
    Base.metadata.create_all(bind=engine)
    migrate_schema()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
