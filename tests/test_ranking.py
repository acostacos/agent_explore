from datetime import datetime, timedelta, timezone

from app.arxiv_client import ArxivPaper, build_search_query
from app.citations import CitationInfo, strip_arxiv_version
from app.interests import normalize_keyword, parse_keywords
from app.ranking import keyword_match_score, rank_papers


def _paper(title: str, abstract: str, days_ago: int, arxiv_id: str = "2401.00001") -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=title,
        authors=["A Researcher"],
        abstract=abstract,
        categories=["cs.AI"],
        published_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        pdf_url="",
        abs_url="",
    )


def test_parse_keywords_from_mixed_input():
    assert parse_keywords("LLM Agents, diffusion models\nRAG") == [
        "llm agents",
        "diffusion models",
        "rag",
    ]
    assert normalize_keyword("  Retrieval   Augmented  ") == "retrieval augmented"


def test_build_search_query_with_keywords():
    q = build_search_query(["cs.AI", "cs.LG"], ["llm agents", "rag"])
    assert "cat:cs.AI" in q
    assert 'all:"llm agents"' in q
    assert "all:rag" in q
    assert " AND " in q


def test_keyword_match_prefers_title_hits():
    paper = _paper(
        "LLM Agents for Tool Use",
        "We study planning in language agents.",
        days_ago=3,
    )
    score, matched = keyword_match_score(paper, ["llm agents", "diffusion"])
    assert matched == ["llm agents"]
    assert score >= 3.0


def test_rank_prioritizes_new_well_cited_and_keyword_matches():
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    hot = _paper(
        "Efficient Retrieval Augmented Generation",
        "A new RAG system for production.",
        days_ago=5,
        arxiv_id="2401.11111",
    )
    obscure = _paper(
        "Notes on Matrix Algebra",
        "We revisit elementary linear algebra facts.",
        days_ago=4,
        arxiv_id="2401.22222",
    )
    old_famous = _paper(
        "Attention Is Not All You Need Anymore",
        "A classic transformer follow-up with retrieval augmented generation.",
        days_ago=400,
        arxiv_id="2001.33333",
    )

    citations = {
        "2401.11111": CitationInfo(citation_count=40, influential_citation_count=8),
        "2401.22222": CitationInfo(citation_count=0, influential_citation_count=0),
        "2001.33333": CitationInfo(citation_count=500, influential_citation_count=80),
    }
    ranked = rank_papers(
        [obscure, old_famous, hot],
        keywords=["retrieval augmented generation"],
        citations=citations,
        now=now,
    )
    assert ranked[0].paper.arxiv_id == "2401.11111"
    assert "retrieval augmented generation" in ranked[0].matched_keywords


def test_strip_arxiv_version():
    assert strip_arxiv_version("2401.00001v3") == "2401.00001"
