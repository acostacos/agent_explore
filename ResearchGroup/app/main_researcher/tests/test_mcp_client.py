import httpx
import pytest

from mcp_client import client


class FakeCreds:
    def get_frozen_credentials(self):
        from botocore.credentials import ReadOnlyCredentials

        return ReadOnlyCredentials("AKIDEXAMPLE", "secret", "token")


class FakeSession:
    def get_credentials(self):
        return FakeCreds()


def test_no_endpoint_returns_none(monkeypatch):
    monkeypatch.delenv(client.GATEWAY_URL_ENV, raising=False)
    monkeypatch.delenv(client.LOCAL_URL_ENV, raising=False)
    assert client.get_streamable_http_mcp_client() is None


def test_gateway_url_uses_sigv4(monkeypatch):
    monkeypatch.delenv(client.LOCAL_URL_ENV, raising=False)
    monkeypatch.setenv(client.GATEWAY_URL_ENV, "https://gw.example.com/mcp")
    mcp = client.get_streamable_http_mcp_client()
    conn = mcp.connections["research_tools"]
    assert conn["url"] == "https://gw.example.com/mcp"
    assert isinstance(conn["auth"], client.SigV4HttpxAuth)


def test_local_url_has_no_auth(monkeypatch):
    monkeypatch.setenv(client.LOCAL_URL_ENV, "http://localhost:8000/mcp")
    conn = client.get_streamable_http_mcp_client().connections["research_tools"]
    assert "auth" not in conn


def test_sigv4_auth_adds_signature_headers():
    auth = client.SigV4HttpxAuth("bedrock-agentcore", "ap-southeast-1", session=FakeSession())
    request = httpx.Request(
        "POST", "https://gw.example.com/mcp", json={"jsonrpc": "2.0"}, headers={"accept": "application/json"}
    )
    signed = next(auth.auth_flow(request))
    assert signed.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "bedrock-agentcore" in signed.headers["authorization"]
    assert "ap-southeast-1" in signed.headers["authorization"]
    assert signed.headers["x-amz-security-token"] == "token"
    assert "x-amz-date" in signed.headers


def test_sigv4_auth_requires_credentials():
    class NoCreds:
        def get_credentials(self):
            return None

    auth = client.SigV4HttpxAuth("bedrock-agentcore", "ap-southeast-1", session=NoCreds())
    with pytest.raises(RuntimeError):
        next(auth.auth_flow(httpx.Request("GET", "https://gw.example.com/mcp")))
