import pytest

import credentials


def test_workload_token_from_headers_case_insensitive():
    assert credentials.workload_token_from_headers({"WorkloadAccessToken": "t"}) == "t"
    assert credentials.workload_token_from_headers({"X-Amz-Bedrock-AgentCore-Identity-WAT": "w"}) == "w"
    assert credentials.workload_token_from_headers({}) is None
    assert credentials.workload_token_from_headers(None) is None


async def test_env_var_wins(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "from-env")
    assert await credentials.get_brave_api_key() == "from-env"


async def test_identity_used_when_no_env(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    async def fake_identity(headers):
        return "from-identity"

    monkeypatch.setattr(credentials, "_from_identity", fake_identity)
    assert await credentials.get_brave_api_key({"WorkloadAccessToken": "x"}) == "from-identity"


async def test_secrets_manager_fallback(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    async def none(headers):
        return None

    monkeypatch.setattr(credentials, "_from_identity", none)
    monkeypatch.setattr(credentials, "_from_secrets_manager", lambda: "from-sm")
    assert await credentials.get_brave_api_key() == "from-sm"


async def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SECRET_ARN", raising=False)

    async def none(headers):
        return None

    monkeypatch.setattr(credentials, "_from_identity", none)
    with pytest.raises(credentials.MissingApiKeyError):
        await credentials.get_brave_api_key()
