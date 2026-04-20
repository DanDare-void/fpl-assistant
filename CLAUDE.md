# FPL Assistant — Claude Code Context

## Project Overview

An AI-powered Fantasy Premier League assistant running on a Raspberry Pi 5 (4GB).
It fetches and caches FPL data, provides conversational analysis via a chat UI,
and auto-generates weekly reports ahead of gameweek deadlines.

**Stack:** Python (FastAPI) backend + React frontend, served as a single deployable
unit. Claude API (Anthropic) powers all AI analysis.

---

## Architecture

```
fpl-assistant/
├── backend/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── fpl/
│   │   ├── client.py            # FPL API HTTP client
│   │   ├── cache.py             # SQLite caching layer
│   │   ├── models.py            # Pydantic models for FPL data
│   │   └── enrichment.py        # Derived stats (form, FDR, value)
│   ├── claude/
│   │   ├── client.py            # Anthropic API client (streaming)
│   │   ├── context.py           # Builds structured FPL context for prompts
│   │   └── prompts.py           # System prompts for chat and report modes
│   ├── scheduler.py             # APScheduler — weekly report + cache refresh
│   ├── routes/
│   │   ├── chat.py              # POST /api/chat (SSE streaming)
│   │   ├── report.py            # GET /api/report/latest
│   │   ├── squad.py             # GET /api/squad, fixtures, players
│   │   └── health.py            # GET /api/health
│   └── db.py                    # SQLite connection + schema init
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── Chat.jsx         # Conversational chat interface
│   │   │   ├── ReportPanel.jsx  # Weekly auto-generated report display
│   │   │   ├── SquadView.jsx    # Current squad at-a-glance
│   │   │   └── Fixtures.jsx     # Next 6 GW fixture difficulty
│   │   └── api.js               # Frontend API client
│   └── dist/                    # Built static files (served by FastAPI)
├── scripts/
│   ├── setup_pi.sh              # Pi 5 initial setup script
│   └── seed_cache.py            # Pre-populate SQLite on first run
├── .env.example
├── requirements.txt
├── package.json                 # Frontend build
└── CLAUDE.md                    # This file
```

---

## Environment Variables

```env
ANTHROPIC_API_KEY=sk-...          # Required — Anthropic API key
FPL_TEAM_ID=12345                 # Your FPL team ID (find in the FPL URL)
FPL_LEAGUE_ID=67890               # Your mini-league ID (optional)
CACHE_REFRESH_HOURS=4             # How often to refresh FPL data cache
REPORT_HOURS_BEFORE_DEADLINE=24   # When to auto-generate the weekly report
DATABASE_PATH=./data/fpl.db       # SQLite database location
HOST=0.0.0.0                      # Bind address (0.0.0.0 for Pi network access)
PORT=8000
```

---

## FPL API Reference

Base URL: `https://fantasy.premierleague.com/api/`

All endpoints are public (no auth required for read operations).

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
| `me/` | Your team data (requires session auth — write phase) |

**Important:** The FPL API is unofficial and undocumented. It can change without
notice. Always handle HTTP errors and unexpected schema changes gracefully.

---

## Claude API Usage

### Models
- **Haiku (`claude-haiku-4-5-20251001`)** — chat responses, quick lookups.
  Fast and cheap, sufficient for most conversational queries.
- **Sonnet (`claude-sonnet-4-6`)** — weekly report generation, deep analysis.
  Used sparingly due to cost.

### Chat (streaming)
Use SSE streaming for all chat responses. The frontend expects `text/event-stream`.

```python
async with anthropic_client.messages.stream(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    system=build_system_prompt(fpl_context),
    messages=conversation_history,
) as stream:
    async for text in stream.text_stream:
        yield f"data: {text}\n\n"
```

### Context injection pattern
Always inject structured FPL data into the system prompt, not the user message.
The context builder (`claude/context.py`) should produce a compact JSON summary
covering: current squad, budget, gameweek, upcoming fixtures (next 6 GW with FDR),
top transfer targets by form/value, chip status, and mini-league position.

Keep context under ~2000 tokens for Haiku chat. Sonnet reports can use more.

### Weekly report prompt goal
The report should cover: recommended transfers (with reasoning), captain pick,
chip recommendation if applicable, players to watch, and fixture analysis for
the next 3 gameweeks. Tone: concise, opinionated, like a trusted co-manager.

---

## Data Layer (SQLite Cache)

Cache aggressively — the FPL API can be slow and rate-limiting is a concern.

| Table | Refresh frequency | Notes |
|---|---|---|
| `bootstrap` | Every 4 hours | Players, teams, GW info |
| `fixtures` | Daily | Full season fixture list |
| `squad` | Every 4 hours | Your current picks |
| `player_history` | On demand | Per-player detail, cache 24h |
| `live_scores` | Every 5 mins during active GW | Only when a GW is live |
| `reports` | Per generation | Store generated reports as text |

Use a `cache_meta` table to track last-fetched timestamps per data type.

---

## Raspberry Pi 5 Deployment

Target: **Raspberry Pi 5, 4GB RAM**, running Raspberry Pi OS Lite (64-bit).

### Services
Run backend and frontend build as systemd services.

```ini
# /etc/systemd/system/fpl-assistant.service
[Unit]
Description=FPL Assistant Backend
After=network.target

[Service]
WorkingDirectory=/home/pi/fpl-assistant
EnvironmentFile=/home/pi/fpl-assistant/.env
ExecStart=/home/pi/fpl-assistant/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
User=pi

[Install]
WantedBy=multi-user.target
```

### Network access
The app binds to `0.0.0.0:8000`. Access locally on the home network or
remotely via the WireGuard VPN already configured on the ASUS ZenWiFi XT9.

### Resource constraints
- Avoid keeping large in-memory datasets — use SQLite queries to fetch what's needed
- Haiku responses are fast and cheap; don't batch unnecessary Sonnet calls
- The Pi 5 4GB is comfortably sufficient for this workload

---

## Development Conventions

### Python
- Python 3.11+
- Use `async/await` throughout (FastAPI + httpx for async HTTP)
- Pydantic v2 for all data models
- Type hints everywhere
- `ruff` for linting

### React
- React 18, functional components, hooks only
- Tailwind CSS for styling
- No heavy component libraries — keep the bundle small
- `vite` for dev and build
- Built dist served directly by FastAPI via `StaticFiles`

### Error handling
- FPL API failures should return stale cached data if available, never crash
- Claude API errors should surface as user-friendly chat messages
- Log to file (rotating, max 10MB) not just stdout on the Pi

### Testing
- Backend: `pytest` + `httpx` test client
- FPL client: mock the HTTP responses, don't hit the real API in tests
- Frontend: not required at this stage

---

## Current Build Status

- [ ] FPL data layer (client, cache, models)
- [ ] FastAPI backend + routes
- [ ] Claude integration (chat + report)
- [ ] APScheduler (cache refresh + report generation)
- [ ] React frontend (chat UI + report panel)
- [ ] Pi deployment + systemd setup

**Phase 2 (later):** Write layer — authenticated transfers, captain/bench changes,
chip activation. Auth via FPL session cookie (`pl_profile` + `sessionid`).
