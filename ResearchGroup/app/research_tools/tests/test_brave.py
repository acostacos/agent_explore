import httpx
import pytest
import respx

import brave

NEWS = {
    "results": [
        {
            "title": "Model X released",
            "url": "https://example.com/x",
            "description": "Big news",
            "age": "2 days ago",
            "meta_url": {"hostname": "example.com"},
            "extra": "ignored",
        }
    ]
}
WEB = {"web": {"results": [{"title": "T", "url": "https://u", "description": "D", "age": "1 day ago"}]}}


@respx.mock
async def test_news_search_shapes_results_and_sends_key():
    route = respx.get(brave.BRAVE_NEWS_URL).mock(return_value=httpx.Response(200, json=NEWS))
    out = await brave.news_search("llm", "secret", freshness="pw", count=5)
    assert out == [
        {
            "title": "Model X released",
            "url": "https://example.com/x",
            "description": "Big news",
            "age": "2 days ago",
            "source": "example.com",
        }
    ]
    req = route.calls[0].request
    assert req.headers["X-Subscription-Token"] == "secret"
    assert req.url.params["freshness"] == "pw"
    assert req.url.params["count"] == "5"


@respx.mock
async def test_web_search_shapes_results():
    respx.get(brave.BRAVE_WEB_URL).mock(return_value=httpx.Response(200, json=WEB))
    out = await brave.web_search("llm", "k")
    assert out[0]["title"] == "T"


@respx.mock
async def test_empty_results():
    respx.get(brave.BRAVE_NEWS_URL).mock(return_value=httpx.Response(200, json={}))
    assert await brave.news_search("x", "k") == []


async def test_invalid_freshness_rejected():
    with pytest.raises(ValueError):
        await brave.news_search("x", "k", freshness="bogus")


@respx.mock
async def test_count_is_clamped():
    route = respx.get(brave.BRAVE_NEWS_URL).mock(return_value=httpx.Response(200, json={}))
    await brave.news_search("x", "k", count=999)
    assert route.calls[0].request.url.params["count"] == "20"


@respx.mock
async def test_http_error_propagates():
    respx.get(brave.BRAVE_NEWS_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(httpx.HTTPStatusError):
        await brave.news_search("x", "k")
