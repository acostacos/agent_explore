from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

import arxiv

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2610.00001v1</id>
    <published>2026-10-07T10:00:00Z</published>
    <title>A  Great
      Paper</title>
    <summary>  We do things.
      Well. </summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <link href="http://arxiv.org/abs/2610.00001v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2610.00001v1" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.AI"/>
    <category term="cs.AI"/>
    <category term="cs.LG"/>
  </entry>
</feed>
"""

NOW = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_build_search_query_has_categories_text_and_date_range():
    q = arxiv.build_search_query(
        "agents", ["cs.AI", "cs.MA"], datetime(2026, 10, 5, 0, 0), datetime(2026, 10, 12, 0, 0)
    )
    assert "(cat:cs.AI OR cat:cs.MA)" in q
    assert 'all:"agents"' in q
    assert "submittedDate:[202610050000 TO 202610120000]" in q


def test_build_search_query_without_text_omits_all_clause():
    q = arxiv.build_search_query("  ", ["cs.AI"], datetime(2026, 10, 5), datetime(2026, 10, 12))
    assert "all:" not in q


def test_parse_feed_shapes_entries():
    papers = arxiv.parse_feed(ATOM)
    assert len(papers) == 1
    p = papers[0]
    assert p["title"] == "A Great Paper"
    assert p["abstract"] == "We do things. Well."
    assert p["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert p["pdf"] == "http://arxiv.org/pdf/2610.00001v1"
    assert p["categories"] == ["cs.AI", "cs.LG"]
    assert p["primary_category"] == "cs.AI"


@respx.mock
async def test_search_sends_expected_params():
    route = respx.get(arxiv.ARXIV_URL).mock(return_value=httpx.Response(200, text=ATOM))
    papers = await arxiv.search("", None, days_back=7, max_results=500, now=NOW)
    assert len(papers) == 1
    params = parse_qs(urlparse(str(route.calls[0].request.url)).query)
    assert params["sortBy"] == ["submittedDate"]
    assert params["max_results"] == ["100"]  # clamped
    assert "submittedDate:[202610050000 TO 202610120000]" in params["search_query"][0]
    assert "cat:cs.CL" in params["search_query"][0]


@respx.mock
async def test_search_raises_on_http_error():
    respx.get(arxiv.ARXIV_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await arxiv.search(now=NOW)
