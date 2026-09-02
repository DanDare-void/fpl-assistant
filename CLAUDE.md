# FPL Assistant — Claude Code Context

## Project Overview

An AI-powered Fantasy Premier League assistant running locally (Beelink mini PC, WSL2 Ubuntu).
It fetches and caches FPL data, provides conversational analysis via a chat UI,
auto-generates weekly reports, and supports authenticated team management (transfers,
captain picks, chip activation) with a human-confirm flow.

**Stack:** Python (FastAPI) backend + React frontend, served as a single deployable
unit. Claude API (Anthropic) powers all AI analysis.

---

## Architecture

```
fpl-assistant/
├── backend/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── db.py                    # SQLite connection + schema init
│   ├── fpl/
│   │   ├── client.py            # FPL API HTTP client (read, unauthenticated)
│   │   ├── cache.py             # SQLite caching layer
│   │   ├── models.py            # Pydantic models for FPL data
│   │   ├── enrichment.py        # Derived stats (form, FDR, value)
│   │   ├── session.py           # In-memory Bearer token store
│   │   └── writer.py            # Authenticated FPL write client
│   ├── claude/
│   │   ├── client.py            # Anthropic API client (streaming)
│   │   ├── context.py           # Builds structured FPL context for prompts
│   │   ├── prompts.py           # System prompts for chat and report modes
│   │   └── planner.py           # Transfer + captain recommendation generator
│   ├── routes/
│   │   ├── chat.py              # POST /api/chat (SSE streaming)
│   │   ├── report.py            # GET /api/report/latest, POST /api/report/generate
│   │   ├── squad.py             # GET /api/squad, /api/fixtures, /api/players, /api/fdr
│   │   ├── health.py            # GET /api/health
│   │   ├── auth.py              # POST/DELETE/GET /api/auth/session
│   │   └── manage.py            # GET /api/manage/recommendations, POST confirm endpoints
│   └── scheduler.py             # APScheduler — deferred, not yet implemented
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js               # Frontend API client
│   │   └── components/
│   │       ├── Chat.jsx         # Conversational chat interface
│   │       ├── ReportPanel.jsx  # Weekly auto-generated report display
│   │       ├── SquadView.jsx    # Current squad at-a-glance
│   │       ├── Fixtures.jsx     # Next 6 GW fixture difficulty (FDR table)
│   │       └── Manage.jsx       # Team management — auth, recommendations, confirm
│   └── dist/                    # Built static files (served by FastAPI)
├── .env.example
├── requirements.txt
├── package.json                 # Frontend build
└── CLAUDE.md                    # This file
```

---

## Environment Variables

```env
ANTHROPIC_API_KEY=sk-...          # Required — Anthropic API key
FPL_TEAM_ID=8414272               # FPL team ID — REASSIGNED EVERY SEASON, update each August (2026/27: WeComeInPeace)
FPL_LEAGUE_ID=                    # Mini-league ID (optional, not yet configured)
CACHE_REFRESH_HOURS=4             # How often to refresh FPL data cache
REPORT_HOURS_BEFORE_DEADLINE=24   # When to auto-generate the weekly report
DATABASE_PATH=./data/fpl.db       # SQLite database location
HOST=0.0.0.0
PORT=8000
```

---

## FPL API Reference

Base URL: `https://fantasy.premierleague.com/api/`

All read endpoints are public (no auth required).

| Endpoint | Description |
|---|---|
| `bootstrap-static/` | Master data — all players, teams, gameweeks, element types |
| `fixtures/` | All fixtures for the season |
| `fixtures/?event={gw}` | Fixtures for a specific gameweek |
| `entry/{team_id}/` | Team metadata |
| `entry/{team_id}/event/{gw}/picks/` | Squad picks for a given gameweek |
| `entry/{team_id}/transfers/` | Transfer history |
| `entry/{team_id}/history/` | Season history + chip usage |
| `leagues-classic/{league_id}/standings/` | Mini-league standings |
| `element-summary/{player_id}/` | Full player history + fixtures |
| `event/{gw}/live/` | Live gameweek scores |
| `me/` | Authenticated user profile |
| `my-team/{team_id}/` | Authenticated picks with selling prices |
| `transfers/` | POST — submit transfers (authenticated) |

**Important:** The FPL API is unofficial and undocumented. It can change without
notice. Always handle HTTP errors and unexpected schema changes gracefully.

### Authentication (write operations)

FPL now uses **OAuth2 JWT Bearer tokens** via the `x-api-authorization` header.
The old `pl_profile` + `sessionid` cookie approach no longer works.

To get a token:
1. Log into `fantasy.premierleague.com` in Chrome
2. DevTools (F12) → Network → Fetch/XHR → refresh page
3. Click any `/api/` request → Request Headers → copy `x-api-authorization` value

Tokens expire after ~8 hours. The frontend stores them in `localStorage` and
auto-submits on load. When expired, the user is dropped back to the login form.

The token is stored **in memory only** on the backend (`backend/fpl/session.py`) —
never persisted to disk or database.

---

## Claude API Usage

### Models
- **Haiku (`claude-haiku-4-5-20251001`)** — chat responses, quick lookups.
- **Sonnet (`claude-sonnet-4-6`)** — weekly report generation, transfer planning.

### Chat (streaming)
SSE streaming via `POST /api/chat`. Frontend expects `text/event-stream`.

### Context injection pattern
Inject structured FPL data into the system prompt, not the user message.
Context builder (`claude/context.py`) produces compact JSON: squad, budget,
gameweek, FDR fixtures (next 6 GW), top transfer targets, chip status.

Keep context under ~2000 tokens for Haiku chat. Sonnet can use more.

### Transfer planner
`claude/planner.py` uses Sonnet to produce structured JSON recommendations:
captain, vice-captain, up to N transfers (N = free transfers available),
chip suggestion, and a summary. Returns strict JSON — no prose.

Transfers always target the **next** gameweek (`is_next=True`), not the current one.

---

## Data Layer (SQLite Cache)

| Table | Refresh frequency | Notes |
|---|---|---|
| `bootstrap` | Every 4 hours | Players, teams, GW info |
| `fixtures` | Daily | Full season fixture list |
| `squad` | Every 4 hours | Current picks |
| `player_history` | On demand | Per-player detail, cache 24h |
| `live_scores` | Every 5 mins during active GW | Only when a GW is live |
| `reports` | Per generation | Stored as markdown text |

Cache-first pattern throughout: serve stale data on FPL API failures rather than erroring.

---

## Development

### Running locally
```bash
# Backend
source venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Frontend dev (hot reload, proxies /api to :8000)
cd frontend && npm run dev

# Frontend production build (served by FastAPI at :8000)
cd frontend && npm run build
```

### Conventions
- Python 3.12, `async/await` throughout, Pydantic v2, type hints, `ruff`
- React 18, functional components + hooks, Tailwind CSS v3, Vite 5
- FPL API failures → stale cache fallback, never 500
- Claude API errors → user-friendly messages
- Rotating log file (`logs/fpl-assistant.log`, max 10MB)

---

## Current Build Status

- [x] FPL data layer (client, cache, models, enrichment)
- [x] FastAPI backend + routes
- [x] Claude integration (chat + report + transfer planner)
- [x] React frontend (Chat, Squad, Fixtures, Report, Manage tabs)
- [x] Write layer (transfers, captain, bench — confirm flow)
- [ ] APScheduler (cache refresh + report auto-generation) — deferred
- [x] Cluster deployment — runs on the keel k3s cluster (see below)

---

## Deployment (keel cluster)

The app runs on the home k3s cluster (repo: `~/projects/keel-cluster`) as a single
pinned Deployment. See `docs/adr/DECISIONS.md` ADR 0002 for the full rationale.

- **URL:** `http://192.168.50.46:30080` (NodePort — any node IP works, LAN only)
- **Manifests:** `k8s/fpl-assistant.yaml` (namespace `football`, pinned to keel-db —
  the storage tier per keel-cluster ADR 0008, moved from keel-w5 on 2026-09-02; the
  pod carries the `dedicated=db` toleration; SQLite on a `local-path` PV at `/app/data`)
- **Secret:** `fpl-assistant-env`, created from the local `.env`, never committed
- **Deploy/update:** `scripts/deploy-cluster.sh` — rsyncs source to keel-db, builds
  the `Dockerfile` there with podman (native arm64), imports the image into k3s
  containerd (no registry), applies manifests, restarts the deployment
- The Haaland watch CronJob (`k8s/haaland-watch-cronjob.yaml`) is separate and
  unaffected by app deploys

Local dev on the Beelink still works exactly as below — the cluster copy has its own
database and doesn't share state with a locally-run instance.
