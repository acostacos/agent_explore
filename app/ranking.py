"""Rank papers by interest match, recency, and citation traction."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.arxiv_client import ArxivPaper
from app.citations import CitationInfo


@dataclass
class RankedPaper:
    paper: ArxivPaper
    citation_count: int = 0
    influential_citation_count: int = 0
    matched_keywords: list[str] = field(default_factory=list)
    keyword_score: float = 0.0
    citation_score: float = 0.0
    recency_score: float = 0.0
    rank_score: float = 0.0


def _age_days(published_at: datetime | None, now: datetime) -> float:
    if not published_at:
        return 30.0
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    delta = now - published_at.astimezone(timezone.utc)
    return max(delta.total_seconds() / 86400.0, 0.5)


def keyword_match_score(paper: ArxivPaper, keywords: list[str]) -> tuple[float, list[str]]:
    if not keywords:
        return 0.0, []
    haystack = f"{paper.title} {paper.abstract}".lower()
    matched: list[str] = []
    score = 0.0
    for kw in keywords:
        pattern = re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)", re.IGNORECASE)
        hits = pattern.findall(haystack)
        if not hits:
            # Phrase / substring fallback for multi-word interests.
            if kw in haystack:
                hits = [kw]
            else:
                continue
        matched.append(kw)
        title_hit = kw in paper.title.lower()
        # Title matches weigh more; multiple hits add a little.
        score += (3.0 if title_hit else 1.5) + min(len(hits) - 1, 3) * 0.25
    return score, matched


def citation_traction_score(
    citations: CitationInfo,
    published_at: datetime | None,
    now: datetime,
    max_age_days: float = 365.0,
) -> float:
    """Prefer papers that are both new and already well cited (citation velocity)."""
    age = _age_days(published_at, now)
    # Soft age gate: still allow older papers, but decay hard past ~1 year.
    age_factor = math.exp(-age / max_age_days)

    cites = max(citations.citation_count, 0)
    influential = max(citations.influential_citation_count, 0)
    # Citations per day, log-compressed so extreme outliers don't dominate.
    velocity = cites / age
    score = math.log1p(velocity * 7.0) * 2.2  # weekly velocity emphasis
    score += math.log1p(cites) * 0.55
    score += math.log1p(influential) * 0.9
    score *= 0.35 + 0.65 * age_factor
    return score


def recency_score(published_at: datetime | None, now: datetime) -> float:
    age = _age_days(published_at, now)
    # Strong within ~14 days, fades over ~90 days.
    return math.exp(-age / 21.0) * 2.5


def rank_papers(
    papers: list[ArxivPaper],
    keywords: list[str],
    citations: dict[str, CitationInfo],
    now: datetime | None = None,
    require_keyword_match: bool = False,
) -> list[RankedPaper]:
    now = now or datetime.now(timezone.utc)
    ranked: list[RankedPaper] = []

    for paper in papers:
        cite = citations.get(paper.arxiv_id, CitationInfo())
        kw_score, matched = keyword_match_score(paper, keywords)
        if require_keyword_match and keywords and not matched:
            continue
        cite_score = citation_traction_score(cite, paper.published_at, now)
        recent = recency_score(paper.published_at, now)

        # When interests are set, keyword match is the primary gate/boost.
        # Non-matches can still surface if they are unusually well-cited and new,
        # but they stay below solid interest hits.
        if keywords:
            total = kw_score * 2.4 + cite_score * 1.6 + recent * 0.8
            if matched:
                total += 1.5
            else:
                total *= 0.35
        else:
            total = cite_score * 2.0 + recent * 1.2

        ranked.append(
            RankedPaper(
                paper=paper,
                citation_count=cite.citation_count,
                influential_citation_count=cite.influential_citation_count,
                matched_keywords=matched,
                keyword_score=kw_score,
                citation_score=cite_score,
                recency_score=recent,
                rank_score=total,
            )
        )

    ranked.sort(key=lambda r: (r.rank_score, r.citation_count), reverse=True)
    return ranked
