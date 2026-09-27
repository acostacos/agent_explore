"""Telegram Bot API notifications for PaperPulse digests."""

from __future__ import annotations

import logging
from html import escape

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LEN = 4000


def format_digest_html(
    *,
    run_id: int,
    status: str,
    trigger: str,
    keywords: str,
    papers: list[dict],
    app_name: str = "PaperPulse",
) -> str:
    """Build an HTML digest suitable for Telegram parse_mode=HTML."""
    lines = [
        f"<b>{escape(app_name)} digest</b>",
        f"Run #{run_id} · {escape(status)} · {escape(trigger)}",
    ]
    if keywords:
        lines.append(f"Interests: {escape(keywords)}")
    lines.append(f"Papers: {len(papers)}")
    lines.append("")

    for i, paper in enumerate(papers, start=1):
        title = escape(str(paper.get("title") or "Untitled"))
        cites = int(paper.get("citation_count") or 0)
        url = escape(str(paper.get("abs_url") or paper.get("pdf_url") or ""))
        matched = escape(str(paper.get("matched_keywords") or ""))
        link = f'<a href="{url}">{title}</a>' if url else title
        line = f"{i}. {link} ({cites} cites)"
        if matched:
            line += f" — <i>{matched}</i>"
        lines.append(line)

    text = "\n".join(lines)
    if len(text) <= TELEGRAM_MAX_LEN:
        return text
    return text[: TELEGRAM_MAX_LEN - 20] + "\n…(truncated)"


def send_message(text: str, settings: Settings | None = None) -> dict:
    """Send a Telegram message. Returns status dict; never raises for missing config."""
    settings = settings or get_settings()
    if not settings.telegram_enabled:
        logger.info("Telegram not configured; skipping notification")
        return {"ok": False, "skipped": True, "reason": "not_configured"}

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if response.status_code >= 400 or not data.get("ok", False):
                logger.warning("Telegram send failed: %s %s", response.status_code, data)
                return {"ok": False, "skipped": False, "status_code": response.status_code, "response": data}
            return {"ok": True, "skipped": False, "message_id": data.get("result", {}).get("message_id")}
    except Exception as exc:
        logger.exception("Telegram send error")
        return {"ok": False, "skipped": False, "error": str(exc)}


def notify_run_digest(
    *,
    run_id: int,
    status: str,
    trigger: str,
    keywords: str,
    papers: list[dict],
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    text = format_digest_html(
        run_id=run_id,
        status=status,
        trigger=trigger,
        keywords=keywords,
        papers=papers,
        app_name=settings.app_name,
    )
    return send_message(text, settings=settings)
