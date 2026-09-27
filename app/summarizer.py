"""Summarize research papers — LLM when available, extractive otherwise."""

from __future__ import annotations

import re

import httpx

from app.arxiv_client import ArxivPaper
from app.config import Settings


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    parts = SENTENCE_SPLIT.split(cleaned)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def extractive_summary(abstract: str, max_sentences: int = 3) -> str:
    """Pick the most informative sentences from an abstract without an API key."""
    sents = _sentences(abstract)
    if not sents:
        return abstract.strip() or "No abstract available."

    if len(sents) <= max_sentences:
        return " ".join(sents)

    # Prefer sentences with research signal words; fall back to first + middle + last.
    keywords = (
        "propose",
        "present",
        "introduce",
        "achieve",
        "outperform",
        "show",
        "demonstrate",
        "novel",
        "framework",
        "method",
        "approach",
        "results",
        "state-of-the-art",
        "sota",
    )
    scored: list[tuple[float, int, str]] = []
    for i, sent in enumerate(sents):
        lower = sent.lower()
        score = sum(1.0 for kw in keywords if kw in lower)
        # Slight preference for earlier sentences (context setting).
        score += max(0.0, 0.4 - i * 0.05)
        scored.append((score, i, sent))

    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = sorted(scored[:max_sentences], key=lambda x: x[1])
    return " ".join(s for _, _, s in chosen)


async def llm_summary(paper: ArxivPaper, settings: Settings) -> str | None:
    if not settings.llm_enabled:
        return None

    prompt = (
        "Summarize this AI research paper in 3-4 concise sentences for a busy engineer. "
        "Cover: the problem, the approach, and the key result. Avoid hype.\n\n"
        f"Title: {paper.title}\n"
        f"Authors: {', '.join(paper.authors[:8])}\n"
        f"Abstract: {paper.abstract}"
    )

    payload = {
        "model": settings.openai_model,
        "messages": [
            {
                "role": "system",
                "content": "You are a precise research assistant who writes clear paper digests.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 280,
    }

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content or None
    except Exception:
        return None


async def summarize_paper(paper: ArxivPaper, settings: Settings) -> str:
    llm = await llm_summary(paper, settings)
    if llm:
        return llm
    return extractive_summary(paper.abstract)
