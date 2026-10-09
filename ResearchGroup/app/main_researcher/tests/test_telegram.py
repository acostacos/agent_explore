import httpx
import pytest
import respx

import telegram

TOKEN = "123456:SECRET-TOKEN"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def test_chunk_short_message_unchanged():
    assert telegram.chunk_message("hello") == ["hello"]


def test_chunk_empty():
    assert telegram.chunk_message("   \n") == []


def test_chunk_splits_on_blank_lines_within_limit():
    text = "\n\n".join(f"section {i}\n" + "x" * 900 for i in range(10))
    chunks = telegram.chunk_message(text)
    assert len(chunks) > 1
    assert all(len(c) <= telegram.MAX_MESSAGE_LENGTH for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")


def test_chunk_hard_splits_giant_line():
    chunks = telegram.chunk_message("y" * 9000)
    assert all(len(c) <= telegram.SAFE_CHUNK_LENGTH for c in chunks)
    assert sum(len(c) for c in chunks) == 9000


@respx.mock
async def test_send_message_posts_html_to_chat():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    sent = await telegram.send_message("<b>Hi</b>", token=TOKEN, chat_id="42")
    assert sent == 1
    body = route.calls[0].request.content.decode()
    assert '"chat_id":"42"' in body.replace(" ", "")
    assert '"parse_mode":"HTML"' in body.replace(" ", "")


@respx.mock
async def test_send_message_multiple_chunks():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    text = "\n\n".join("z" * 3000 for _ in range(3))
    assert await telegram.send_message(text, token=TOKEN, chat_id="42") == 3
    assert route.call_count == 3


@respx.mock
async def test_html_parse_error_falls_back_to_plain_text():
    responses = [
        httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse entities: x"}),
        httpx.Response(200, json={"ok": True}),
    ]
    route = respx.post(URL).mock(side_effect=responses)
    await telegram.send_message("<b>broken", token=TOKEN, chat_id="1")
    assert route.call_count == 2
    assert "parse_mode" not in route.calls[1].request.content.decode()


@respx.mock
async def test_error_never_leaks_token():
    respx.post(URL).mock(return_value=httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    with pytest.raises(telegram.TelegramError) as exc:
        await telegram.send_message("hi", token=TOKEN, chat_id="1")
    assert "SECRET-TOKEN" not in str(exc.value)
    assert "401" in str(exc.value)


@respx.mock
async def test_network_error_never_leaks_token():
    respx.post(URL).mock(side_effect=httpx.ConnectError("boom " + URL))
    with pytest.raises(telegram.TelegramError) as exc:
        await telegram.send_message("hi", token=TOKEN, chat_id="1")
    assert "SECRET-TOKEN" not in str(exc.value)
    assert exc.value.__cause__ is None


async def test_empty_message_rejected():
    with pytest.raises(telegram.TelegramError):
        await telegram.send_message("  ", token=TOKEN, chat_id="1")


def test_missing_chat_id(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(telegram.TelegramError):
        telegram.get_chat_id()


async def test_token_env_override(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from-env")
    assert await telegram.get_bot_token() == "from-env"


@respx.mock
async def test_failure_notice_escapes_html():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    await telegram.send_failure_notice(RuntimeError("bad <thing> & more"), token=TOKEN, chat_id="1")
    body = route.calls[0].request.content.decode()
    assert "&lt;thing&gt;" in body and "&amp;" in body
