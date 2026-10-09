# research_tools

A FastMCP server deployed as its own AgentCore Runtime (protocol `MCP`) and exposed through the
`research-gateway` AgentCore Gateway. It serves the tools used by `main_researcher`.

| Tool | Description |
| --- | --- |
| `brave_news_search(query, freshness="pw", count=10)` | Brave News Search |
| `brave_web_search(query, freshness="pw", count=10)` | Brave Web Search |
| `arxiv_search(query="", categories=None, days_back=7, max_results=50)` | Recent arXiv papers, newest first |

The server listens on `0.0.0.0:8000/mcp` using stateless streamable HTTP, per the AgentCore MCP runtime contract.

## Brave API key

Resolved in this order (see `credentials.py`):

1. `BRAVE_API_KEY` env var (local development)
2. AgentCore Identity API-key credential provider `BRAVE_PROVIDER_NAME` (default `brave-search-api-key`)
3. Secrets Manager secret `BRAVE_SECRET_ARN` (optional fallback)

## Local run and tests

```bash
cd app/research_tools
uv sync
BRAVE_API_KEY=... uv run python -m server    # serves http://localhost:8000/mcp
uv run pytest
```

Rate limits: Brave free tier is about 1 request/second and arXiv asks for one request every 3 seconds; both are throttled in code.
