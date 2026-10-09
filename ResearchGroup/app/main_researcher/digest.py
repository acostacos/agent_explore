"""Weekly AI research digest: prompts, HTML sanitising and the weekly_digest flow."""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from langchain_core.messages import HumanMessage

import telegram

logger = logging.getLogger(__name__)

MANILA = timezone(timedelta(hours=8))
RECURSION_LIMIT = 80

DIGEST_SYSTEM_PROMPT = """You are a research analyst who writes a weekly AI research digest for a software engineer.

Use your tools to gather material from the last 7 days, then write the digest.

Tool usage:
- Call arxiv_search once with categories ["cs.AI","cs.LG","cs.CL","cs.CV","cs.MA"], days_back=7 and max_results=60.
  Optionally call it again with a focused query (for example "agents", "reasoning", "multimodal") for extra candidates.
- Call brave_news_search with freshness "pw" for 3 to 5 distinct queries (for example "AI model release",
  "large language model", "AI agents", "AI research breakthrough").
- Never invent papers, links or facts. Only use titles and URLs returned by tools.

Selection:
- Notable Papers (5 to 8): pick papers by relevance and significance (new capabilities, strong results, practical impact for
  builders of LLM and agent systems). Prefer a spread of topics over many near-duplicates.
- Headlines (3 to 5): the most important news items of the week; skip duplicates and low-quality sources.

Output format (Telegram HTML, nothing else, no preamble):
<b>AI Research Digest</b> (date range)

<b>TL;DR</b>
- three short bullet lines

<b>Notable Papers</b>
1. <a href="ARXIV_URL">Paper title</a> - one-line why it matters.

<b>Headlines</b>
1. <a href="NEWS_URL">Headline</a> (source) - one-line summary.

Formatting rules:
- Allowed tags only: <b>, <i>, <a href="...">, <code>. No other HTML, no Markdown.
- Escape &, < and > in text as &amp;, &lt; and &gt;.
- Keep each list item on a single line. Use a blank line between sections.
- Keep the whole digest under 3500 characters.
"""

DIGEST_USER_PROMPT = (
    "Write this week's digest. Today is {today} (Asia/Manila). "
    "Cover papers submitted and news published from {start} to {today}."
)

CHAT_SYSTEM_PROMPT = """You are a research assistant that helps follow the latest AI news and research.
You can search recent arXiv papers (arxiv_search) and the web and news (brave_web_search, brave_news_search).
Use the tools when the question needs fresh information, cite titles with links, and never invent sources.
"""

_ALLOWED_TAGS = {"b", "i", "a", "code"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>")


def sanitize_html(text: str) -> str:
    """Coerce model output into the small HTML subset Telegram accepts."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|ul|ol|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"</?(strong)>", lambda m: m.group(0).replace("strong", "b"), text, flags=re.I)
    text = re.sub(r"</?(em)>", lambda m: m.group(0).replace("em", "i"), text, flags=re.I)

    def keep_or_drop(match: re.Match) -> str:
        closing, name, rest = match.group(1), match.group(2).lower(), match.group(3)
        if name not in _ALLOWED_TAGS:
            return ""
        if closing:
            return f"</{name}>"
        if name == "a":
            href = re.search(r'href\s*=\s*"([^"]+)"', rest) or re.search(r"href\s*=\s*'([^']+)'", rest)
            return f'<a href="{href.group(1)}">' if href else ""
        return f"<{name}>"

    text = _TAG_RE.sub(keep_or_drop, text)
    # Escape stray ampersands that are not already entities.
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|#\d+);)", "&amp;", text)
    # Balance tags: drop unmatched closers, close unmatched openers.
    stack: list[str] = []
    out: list[str] = []
    pos = 0
    for m in re.finditer(r"</?(b|i|a|code)(?:\s[^>]*)?>", text):
        out.append(text[pos : m.start()])
        pos = m.end()
        tag = m.group(0)
        name = m.group(1)
        if tag.startswith("</"):
            if name in stack:
                while stack:
                    top = stack.pop()
                    out.append(f"</{top}>")
                    if top == name:
                        break
        else:
            stack.append(name)
            out.append(tag)
    out.append(text[pos:])
    out.extend(f"</{t}>" for t in reversed(stack))
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


def extract_text(content: Any) -> str:
    """Normalise AIMessage content (str or list of content blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


async def build_digest(graph: Any, now: Optional[datetime] = None) -> str:
    """Run the agent graph and return the sanitised digest text."""
    now = (now or datetime.now(MANILA)).astimezone(MANILA)
    prompt = DIGEST_USER_PROMPT.format(
        today=now.strftime("%Y-%m-%d"), start=(now - timedelta(days=7)).strftime("%Y-%m-%d")
    )
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=prompt)]},
        config={"recursion_limit": RECURSION_LIMIT, "configurable": {"thread_id": f"digest-{uuid.uuid4()}"}},
    )
    text = sanitize_html(extract_text(result["messages"][-1].content))
    if not text:
        raise RuntimeError("The agent returned an empty digest")
    return text


async def run_weekly_digest(
    graph_factory: Callable[[], Awaitable[Any]],
    *,
    dry_run: bool = False,
    sender=telegram.send_message,
    failure_notifier=telegram.send_failure_notice,
) -> dict:
    """Build the digest and deliver it to Telegram (deterministically, outside the LLM).

    On any failure a short notice is sent to Telegram (unless dry_run) and the error is re-raised.
    """
    try:
        graph = await graph_factory()
        text = await build_digest(graph)
        if dry_run:
            return {"result": text, "sent": False, "dry_run": True}
        chunks = await sender(text)
        return {"result": text, "sent": True, "chunks": chunks}
    except Exception as exc:
        logger.exception("Weekly digest failed")
        if not dry_run:
            try:
                await failure_notifier(exc)
            except Exception:  # noqa: BLE001 - never mask the original error
                logger.exception("Could not send the failure notice to Telegram")
        raise


__all__ = [
    "CHAT_SYSTEM_PROMPT",
    "DIGEST_SYSTEM_PROMPT",
    "build_digest",
    "extract_text",
    "run_weekly_digest",
    "sanitize_html",
]
