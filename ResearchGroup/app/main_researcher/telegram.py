"""Telegram delivery for the weekly digest.

The bot token is fetched from AgentCore Identity (API-key credential provider that references a
Secrets Manager secret). ``TELEGRAM_BOT_TOKEN`` overrides it for local runs. The chat ID is not secret
and comes from ``TELEGRAM_CHAT_ID``.
"""

import html
import logging
import os
import re
from typing import Optional

import httpx

# httpx logs full request URLs at INFO, and Telegram puts the bot token in the URL path.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096
SAFE_CHUNK_LENGTH = 4000
DEFAULT_PROVIDER_NAME = "telegram-bot-token"


class TelegramError(RuntimeError):
    """Telegram API failure. Messages never contain the bot token."""


def chunk_message(text: str, limit: int = SAFE_CHUNK_LENGTH) -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` characters, preferring blank-line then line boundaries."""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    current = ""
    for block in re.split(r"(?<=\n\n)", text):  # keep blank-line separators with the preceding block
        for piece in _split_long(block, limit):
            if len(current) + len(piece) <= limit:
                current += piece
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = piece
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _split_long(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]
    pieces: list[str] = []
    current = ""
    for line in block.splitlines(keepends=True):
        while len(line) > limit:  # a single enormous line: hard split
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) <= limit:
            current += line
        else:
            pieces.append(current)
            current = line
    if current:
        pieces.append(current)
    return pieces


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def get_bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    from bedrock_agentcore.identity.auth import requires_api_key

    provider = os.getenv("TELEGRAM_PROVIDER_NAME", DEFAULT_PROVIDER_NAME)

    @requires_api_key(provider_name=provider)
    async def _fetch(*, api_key: str) -> str:
        return api_key

    return await _fetch()


def get_chat_id() -> str:
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise TelegramError("TELEGRAM_CHAT_ID is not set")
    return chat_id


async def _post(client: httpx.AsyncClient, token: str, payload: dict) -> httpx.Response:
    try:
        return await client.post(f"{TELEGRAM_API}/bot{token}/sendMessage", json=payload)
    except httpx.HTTPError as exc:
        # Do not chain: the original exception message can embed the request URL (and so the token).
        raise TelegramError(f"Telegram request failed: {type(exc).__name__}") from None


async def send_message(
    text: str,
    *,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> int:
    """Send ``text`` (Telegram HTML) to the configured chat, splitting long messages. Returns chunks sent."""
    chunks = chunk_message(text)
    if not chunks:
        raise TelegramError("Refusing to send an empty message")
    token = token or await get_bot_token()
    chat_id = chat_id or get_chat_id()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        for chunk in chunks:
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            resp = await _post(client, token, payload)
            if resp.status_code == 400 and "parse entities" in resp.text:
                logger.warning("Telegram rejected the HTML; resending chunk as plain text")
                payload.pop("parse_mode")
                payload["text"] = strip_tags(chunk)
                resp = await _post(client, token, payload)
            if resp.status_code != 200:
                try:
                    description = resp.json().get("description", "")
                except ValueError:
                    description = ""
                raise TelegramError(f"Telegram sendMessage failed: HTTP {resp.status_code} {description}".strip())
        return len(chunks)
    finally:
        if owns:
            await client.aclose()


async def send_failure_notice(error: BaseException, **kwargs) -> None:
    reason = html.escape(f"{type(error).__name__}: {error}"[:500])
    await send_message(f"<b>Weekly AI digest failed</b>\n{reason}", **kwargs)
