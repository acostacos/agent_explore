import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import handler  # noqa: E402

ARN = "arn:aws:bedrock-agentcore:ap-southeast-1:123456789012:runtime/main_researcher-AbCdEfGhIj"


def ok_response(body):
    return {"response": io.BytesIO(json.dumps(body).encode())}


def factory_for(client):
    return lambda timeout: client


def test_success_first_attempt():
    client = MagicMock()
    client.invoke_agent_runtime.return_value = ok_response({"result": "x", "sent": True})
    out = handler.run(factory_for(client), ARN, lambda: 900, sleep=lambda s: None)
    assert out == {"status": "ok", "attempt": 1, "sent": True}
    kwargs = client.invoke_agent_runtime.call_args.kwargs
    assert kwargs["agentRuntimeArn"] == ARN
    assert json.loads(kwargs["payload"]) == {"mode": "weekly_digest"}
    assert len(kwargs["runtimeSessionId"]) >= 33
    assert kwargs["runtimeUserId"]


def test_retries_once_then_succeeds():
    client = MagicMock()
    client.invoke_agent_runtime.side_effect = [RuntimeError("boom"), ok_response({"sent": True})]
    sleeps = []
    out = handler.run(factory_for(client), ARN, lambda: 900, sleep=sleeps.append)
    assert out["attempt"] == 2
    assert sleeps == [handler.RETRY_DELAY_SECONDS]
    sessions = {c.kwargs["runtimeSessionId"] for c in client.invoke_agent_runtime.call_args_list}
    assert len(sessions) == 2


def test_fails_after_two_attempts():
    client = MagicMock()
    client.invoke_agent_runtime.side_effect = RuntimeError("down")
    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        handler.run(factory_for(client), ARN, lambda: 900, sleep=lambda s: None)
    assert client.invoke_agent_runtime.call_count == 2


def test_error_body_counts_as_failure():
    client = MagicMock()
    client.invoke_agent_runtime.side_effect = lambda **kw: ok_response({"error": "model exploded"})
    with pytest.raises(RuntimeError, match="model exploded"):
        handler.run(factory_for(client), ARN, lambda: 900, sleep=lambda s: None)
    assert client.invoke_agent_runtime.call_count == 2


def test_no_retry_when_time_is_short():
    client = MagicMock()
    client.invoke_agent_runtime.side_effect = RuntimeError("down")
    times = iter([900, 100])  # second attempt has too little time left
    with pytest.raises(RuntimeError):
        handler.run(factory_for(client), ARN, lambda: next(times), sleep=lambda s: None)
    assert client.invoke_agent_runtime.call_count == 1


def test_attempt_timeout_is_capped():
    seen = []

    def factory(timeout):
        seen.append(timeout)
        client = MagicMock()
        client.invoke_agent_runtime.return_value = ok_response({})
        return client

    handler.run(factory, ARN, lambda: 900, sleep=lambda s: None)
    assert seen == [handler.ATTEMPT_TIMEOUT_SECONDS]
