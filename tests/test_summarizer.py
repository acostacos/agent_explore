from app.summarizer import extractive_summary


def test_extractive_summary_prefers_signal_sentences():
    abstract = (
        "Large language models are widely used today. "
        "We propose a novel framework for efficient retrieval-augmented generation. "
        "Experiments demonstrate that our approach outperforms strong baselines on three benchmarks. "
        "Finally we discuss limitations and future work."
    )
    summary = extractive_summary(abstract, max_sentences=2)
    assert "propose a novel framework" in summary
    assert "outperforms strong baselines" in summary


def test_extractive_summary_handles_short_abstract():
    abstract = "We study transformers."
    assert extractive_summary(abstract) == abstract


def test_build_search_query():
    from app.arxiv_client import build_search_query

    assert build_search_query(["cs.AI", "cs.LG"]) == "cat:cs.AI OR cat:cs.LG"
