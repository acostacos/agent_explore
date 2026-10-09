# Brave Search API setup

You need one Brave Search API key. `research_tools` sends it in the `X-Subscription-Token` header.

## Steps

1. Create an account at the [Brave Search API dashboard](https://api-dashboard.search.brave.com/) and verify your email
   (Quickstart, step 1).
2. Open the **Plans** page and activate a plan. A credit card is required even for plans that include free credits.
   Brave says the card is an anti-fraud check and is not charged while you stay within free usage
   ([Brave Search API](https://brave.com/search/api/)).
   The Search plan covers Web Search and News Search.
3. Open **API Keys**, choose **Add API Key**, and name it (for example `agent-explore-weekly-digest`). Copy the key.
   One key per environment makes it easy to revoke a single key later.
4. Test the key (do not paste the real key into shared terminals or commit it):

   ```powershell
   $env:BRAVE_API_KEY = "<your key>"
   curl.exe "https://api.search.brave.com/res/v1/news/search?q=artificial+intelligence&freshness=pw&count=3" `
     -H "Accept: application/json" -H "X-Subscription-Token: $env:BRAVE_API_KEY"
   ```

   You should get JSON with a `results` array. HTTP 401 means the header name is wrong (it is not `Authorization`),
   the key was copied with whitespace, or no plan is active.
5. Store the key in AWS Secrets Manager as described in [secrets-and-agentcore-identity.md](secrets-and-agentcore-identity.md).

## Facts this project relies on

- Auth header is `X-Subscription-Token` ([Authentication](https://api-dashboard.search.brave.com/documentation/guides/authentication)).
- News endpoint: `GET https://api.search.brave.com/res/v1/news/search`. `freshness` accepts `pd` (24 hours),
  `pw` (7 days), `pm` (31 days), `py` (365 days) or a custom `YYYY-MM-DDtoYYYY-MM-DD` range. `count` is 1 to 50
  ([News search reference](https://api-dashboard.search.brave.com/api-reference/news/news_search/get)).
  `research_tools` accepts only `pd`, `pw`, `pm`, `py` and caps `count` at 20.
- Rate limits depend on your plan and use a one-second sliding window; a 429 response includes `X-RateLimit-Reset`
  ([Rate limiting](https://api-dashboard.search.brave.com/documentation/guides/rate-limiting)).
  Plan details and prices change, so check the [Plans page](https://api-dashboard.search.brave.com/) before subscribing.
  The server spaces calls about 1.1 seconds apart, which is safe on any plan. A weekly digest makes roughly 5 to 8
  Brave requests per run, so usage is far below any monthly allowance.
- Rotate keys regularly and revoke a key immediately if it leaks (same Authentication guide).

## Local development

For a local `research_tools` server, set `BRAVE_API_KEY` in your shell. The deployed runtime never uses this variable;
it reads the key from AgentCore Identity.

Sources are listed in [sources.md](sources.md).
