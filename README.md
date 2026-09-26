# PaperPulse — AI Research Paper Agent

Weekly agent that scans the latest AI papers on [arXiv](https://arxiv.org), ranks them by your interests and citation traction, writes a short summary of each pick, and surfaces them in a simple web UI.

## Features

- **Interest keywords** — load topics via the UI, `data/interests.txt`, or `INTEREST_KEYWORDS`
- **Citation-aware ranking** — enriches candidates with Semantic Scholar citations and prioritizes **new, well-cited** papers (citation velocity + recency)
- **Weekly scheduled research** — APScheduler runs every Monday at 09:00 UTC (configurable)
- **Manual runs** — trigger a scan anytime from the UI or API
- **Summaries** — extractive summaries by default; optional OpenAI LLM digests when `OPENAI_API_KEY` is set
- **Tracking** — mark papers read/unread, save for later, browse past runs
- **arXiv categories** — defaults to `cs.AI`, `cs.LG`, `cs.CL`, `cs.CV`

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Open [http://localhost:8000](http://localhost:8000).

1. Add interest keywords in the **Interests** section (or edit `data/interests.txt`)
2. Click **Run research now**
3. Digests are ranked with citation counts and matched keywords shown on each card

The scheduler keeps doing this on the weekly cadence while the app is running.

## How ranking works

Each run:

1. Pulls a candidate pool from arXiv (interest keyword query + recent category sweep)
2. Looks up citation counts on Semantic Scholar
3. Scores papers by keyword match, **citation velocity** (cites / age), influential cites, and recency
4. Keeps the top `PAPERS_PER_RUN` new papers and summarizes them

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | empty | Enables richer LLM summaries |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used when LLM mode is on |
| `PAPERS_PER_RUN` | `20` | Max papers kept per run after ranking |
| `ARXIV_CATEGORIES` | `cs.AI,cs.LG,cs.CL,cs.CV` | Categories to scan |
| `INTEREST_KEYWORDS` | empty | Seed interests (comma/newline separated) |
| `INTERESTS_FILE` | `./data/interests.txt` | Plain-text interests file |
| `SEMANTICSCHOLAR_API_KEY` | empty | Optional, higher citation API rate limits |
| `REQUIRE_KEYWORD_MATCH` | `false` | Drop papers with no interest match |
| `SCHEDULE_DAY_OF_WEEK` | `mon` | Cron day for weekly job |
| `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` | `9` / `0` | Scheduler time |
| `DATABASE_URL` | `sqlite:///./data/papers.db` | SQLite (or other SQLAlchemy URL) |

## API

- `GET /api/health` — health + next scheduled run
- `GET /api/interests` / `PUT /api/interests` — read or replace interest keywords
- `GET /api/runs` — research run history
- `GET /api/runs/{id}` — run detail with papers
- `GET /api/papers` — list papers (`?saved=true`, `?unread=true`)
- `PATCH /api/papers/{id}` — `{ "is_read": true, "is_saved": false }`
- `POST /api/research/run` — start a manual research run

## Tests

```bash
pytest -q
```

## Project layout

```
app/
  agent.py          # fetch → cite → rank → summarize → persist
  arxiv_client.py   # arXiv Atom API client
  citations.py      # Semantic Scholar citation enrichment
  ranking.py        # interest + citation + recency scoring
  interests.py      # keyword load/sync helpers
  summarizer.py     # extractive + optional LLM summaries
  scheduler.py      # weekly APScheduler job
  main.py           # FastAPI + UI routes
  models.py         # SQLAlchemy models
  templates/        # Jinja UI
  static/           # CSS / JS
data/
  interests.txt     # editable interest keywords
```
