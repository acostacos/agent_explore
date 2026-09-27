from app.telegram import format_digest_html, send_message


def test_format_digest_html_includes_papers_and_keywords():
    text = format_digest_html(
        run_id=3,
        status="completed",
        trigger="scheduled",
        keywords="llm agents, rag",
        papers=[
            {
                "title": "Agents & Tools",
                "citation_count": 12,
                "abs_url": "https://arxiv.org/abs/2401.00001",
                "matched_keywords": "llm agents",
            }
        ],
        app_name="PaperPulse",
    )
    assert "PaperPulse digest" in text
    assert "Run #3" in text
    assert "llm agents, rag" in text
    assert "Agents &amp; Tools" in text
    assert "12 cites" in text
    assert "https://arxiv.org/abs/2401.00001" in text


def test_send_message_skips_when_not_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    result = send_message("hello", settings=settings)
    assert result["skipped"] is True
    assert result["ok"] is False
