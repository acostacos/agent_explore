import pytest

import main


class Ctx:
    session_id = "s1"


async def test_weekly_digest_mode_routes_to_digest(monkeypatch):
    seen = {}

    async def fake_run(factory, dry_run=False):
        seen["factory"] = factory
        seen["dry_run"] = dry_run
        return {"result": "ok"}

    async def fail_chat(*a, **k):
        raise AssertionError("chat flow must not run")

    monkeypatch.setattr(main, "run_weekly_digest", fake_run)
    monkeypatch.setattr(main, "run_chat", fail_chat)
    out = await main.invoke({"mode": "weekly_digest", "dry_run": True}, Ctx())
    assert out == {"result": "ok"}
    assert seen["dry_run"] is True and seen["factory"] is main.build_digest_graph


async def test_default_dry_run_is_false(monkeypatch):
    seen = {}

    async def fake_run(factory, dry_run=False):
        seen["dry_run"] = dry_run
        return {}

    monkeypatch.setattr(main, "run_weekly_digest", fake_run)
    await main.invoke({"mode": "weekly_digest"}, Ctx())
    assert seen["dry_run"] is False


async def test_dry_run_must_be_bool():
    with pytest.raises(ValueError):
        await main.invoke({"mode": "weekly_digest", "dry_run": "yes"}, Ctx())


async def test_other_payloads_use_chat_flow(monkeypatch):
    async def fake_chat(payload, context):
        return {"result": f"chat:{payload['prompt']}"}

    async def fail_digest(*a, **k):
        raise AssertionError("digest flow must not run")

    monkeypatch.setattr(main, "run_chat", fake_chat)
    monkeypatch.setattr(main, "run_weekly_digest", fail_digest)
    assert await main.invoke({"prompt": "hi"}, Ctx()) == {"result": "chat:hi"}


def test_normalize_unwraps_cli_style_digest_request():
    wrapped = {"prompt": '{"mode":"weekly_digest","dry_run":true}'}
    assert main.normalize_payload(wrapped) == {"mode": "weekly_digest", "dry_run": True}


@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": "plain question"},
        {"prompt": "{not json"},
        {"prompt": '{"mode":"other"}'},
        {"prompt": '["list"]'},
        {"mode": "weekly_digest", "prompt": '{"mode":"weekly_digest","dry_run":true}'},
        {},
    ],
)
def test_normalize_leaves_other_payloads_alone(payload):
    assert main.normalize_payload(payload) == payload
