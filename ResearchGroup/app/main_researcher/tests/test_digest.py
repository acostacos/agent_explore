from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage

import digest


class FakeGraph:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def ainvoke(self, inputs, config=None):
        self.calls.append((inputs, config))
        return {"messages": [AIMessage(content=self.content)]}


def factory_for(graph):
    async def factory():
        return graph

    return factory


def test_sanitize_converts_and_strips_unsupported_tags():
    raw = "<h1>Title</h1><ul><li>one</li><li>two<br>x</li></ul><strong>bold</strong> <em>it</em><span>s</span>"
    out = digest.sanitize_html(raw)
    assert "<h1>" not in out and "<ul>" not in out and "<span>" not in out and "<li>" not in out
    assert "<b>bold</b>" in out and "<i>it</i>" in out
    assert "- one" in out and "- two" in out


def test_sanitize_keeps_links_and_escapes_ampersands():
    out = digest.sanitize_html('<a href="https://x.org/a?b=1&c=2" target="_blank">T & U</a>')
    assert out == '<a href="https://x.org/a?b=1&amp;c=2">T &amp; U</a>'


def test_sanitize_does_not_double_escape():
    assert digest.sanitize_html("a &amp; b &lt; c") == "a &amp; b &lt; c"


def test_sanitize_balances_tags():
    assert digest.sanitize_html("<b>open only") == "<b>open only</b>"
    assert digest.sanitize_html("close only</b>") == "close only"


def test_extract_text_from_blocks():
    assert digest.extract_text([{"type": "text", "text": "a"}, {"type": "tool_use"}, "b"]) == "ab"


async def test_build_digest_prompt_has_dates_and_fresh_thread():
    graph = FakeGraph("<b>Digest</b>")
    now = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)  # 08:00 Manila
    text = await digest.build_digest(graph, now=now)
    assert text == "<b>Digest</b>"
    inputs, config = graph.calls[0]
    prompt = inputs["messages"][0].content
    assert "2026-10-12" in prompt and "2026-10-05" in prompt
    assert config["configurable"]["thread_id"].startswith("digest-")
    assert config["recursion_limit"] == digest.RECURSION_LIMIT


async def test_empty_digest_is_an_error():
    with pytest.raises(RuntimeError):
        await digest.build_digest(FakeGraph("   "))


async def test_run_weekly_digest_sends():
    sent = []

    async def sender(text):
        sent.append(text)
        return 1

    out = await digest.run_weekly_digest(factory_for(FakeGraph("hello")), sender=sender)
    assert sent == ["hello"]
    assert out["sent"] is True


async def test_dry_run_does_not_send():
    async def sender(text):
        raise AssertionError("must not send")

    out = await digest.run_weekly_digest(factory_for(FakeGraph("hello")), dry_run=True, sender=sender)
    assert out == {"result": "hello", "sent": False, "dry_run": True}


async def test_failure_sends_notice_and_reraises():
    notices = []

    async def notifier(exc):
        notices.append(exc)

    class Boom:
        async def ainvoke(self, *a, **k):
            raise ValueError("model exploded")

    with pytest.raises(ValueError):
        await digest.run_weekly_digest(factory_for(Boom()), failure_notifier=notifier)
    assert len(notices) == 1 and "model exploded" in str(notices[0])


async def test_send_failure_also_triggers_notice():
    notices = []

    async def sender(text):
        raise RuntimeError("telegram down")

    async def notifier(exc):
        notices.append(exc)

    with pytest.raises(RuntimeError):
        await digest.run_weekly_digest(factory_for(FakeGraph("x")), sender=sender, failure_notifier=notifier)
    assert len(notices) == 1


async def test_failing_notifier_does_not_mask_original_error():
    async def notifier(exc):
        raise RuntimeError("notifier broke")

    class Boom:
        async def ainvoke(self, *a, **k):
            raise ValueError("original")

    with pytest.raises(ValueError, match="original"):
        await digest.run_weekly_digest(factory_for(Boom()), failure_notifier=notifier)


async def test_dry_run_failure_sends_no_notice():
    async def notifier(exc):
        raise AssertionError("must not notify in dry_run")

    class Boom:
        async def ainvoke(self, *a, **k):
            raise ValueError("x")

    with pytest.raises(ValueError):
        await digest.run_weekly_digest(factory_for(Boom()), dry_run=True, failure_notifier=notifier)
