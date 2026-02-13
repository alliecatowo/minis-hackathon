# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI personality clones ("minis") built from GitHub profiles. An agentic pipeline analyzes commits, PRs, reviews, blog posts, and more, then creates an AI that thinks, writes, and argues like the developer.

## Commands

```bash
# Dev servers
mise run dev              # Both backend (:8000) and frontend (:3000)
mise run dev-backend      # Backend only
mise run dev-frontend     # Frontend only

# Backend
cd backend && uv run pytest                        # Run all tests
cd backend && uv run pytest tests/test_agent.py    # Run single test file
cd backend && uv run pytest -k "test_name"         # Run test by name
cd backend && uv run alembic upgrade head           # Run database migrations
cd backend && uv run alembic revision --autogenerate -m "description"  # Create migration

# Frontend
cd frontend && pnpm dev       # Dev server
cd frontend && pnpm build     # Production build
cd frontend && pnpm lint      # ESLint

# Deployment
cd frontend && vercel --prod           # Deploy frontend to Vercel
cd backend && fly deploy               # Deploy backend to Fly.io
```

## Project Structure

- `backend/` — FastAPI + SQLAlchemy + PostgreSQL (Python 3.13, uv)
- `frontend/` — Next.js 15 + Tailwind v4 + shadcn/ui (pnpm)
- `mcp-server/` — FastMCP server wrapping Minis API (5 tools)
- `github-app/` — GitHub App webhook server for PR reviews by minis
- `.claude/` — Claude Code skills, commands, and agent definitions

Tooling is managed by mise (see `mise.toml`): pnpm, uv, node 22, python 3.13.

## Architecture

### Pipeline (5 stages)

Creating a mini runs a pipeline defined in `backend/app/synthesis/pipeline.py`:

1. **FETCH** — Ingestion sources pull raw data (GitHub API, blog scraping, etc.)
2. **EXPLORE** — Per-source Explorer agents (ReAct loop with tools) analyze evidence in parallel, producing `ExplorerReport`s
3. **ASSEMBLE** — Memory assembler merges explorer reports into a structured memory document and extracts roles/skills/traits via LLM
4. **SYNTHESIZE** — Chief synthesizer agent cross-references all explorer reports to craft the soul document (personality, style, values)
5. **SAVE** — Persists soul document, memory document, system prompt, and structured data

### Key concepts

- **Soul document** (`spirit_content`): WHO the person is — personality, communication style, values. Written as instructions, not descriptions. Produced by the chief synthesizer.
- **Memory document** (`memory_content`): WHAT the person knows — projects, expertise, opinions, behavioral quotes. Produced by the memory assembler.
- **System prompt** (`system_prompt`): Wraps soul + memory into a four-pillar prompt (Personality, Style, Values, Knowledge). Built by `spirit.build_system_prompt()`.
- **Knowledge graph** (`knowledge_graph_json`): Structured nodes (skills, projects, patterns) and edges extracted by explorers.
- **Principles matrix** (`principles_json`): Decision rules (trigger → action → value) extracted by explorers.

### Agent framework

`backend/app/core/agent.py` provides the ReAct agent loop used by explorers and chat:

- **`AgentTool`** dataclass: `name`, `description`, `parameters` (JSON Schema), `handler` (async callable)
- **`run_agent()`**: Non-streaming loop. Forces `tool_choice="required"` on first turn.
- **`run_agent_streaming()`**: Streaming variant yielding `AgentEvent`s (`tool_call`, `tool_result`, `chunk`, `done`, `error`).

### Explorer system

Explorers extend `Explorer` ABC (`backend/app/synthesis/explorers/base.py`), implement `system_prompt()` and `user_prompt()`, and self-register via `register_explorer()`. Current explorers: `github`, `claude_code`, `blog`, `hackernews`, `stackoverflow`, `devblog`.

### Ingestion sources

Implement `IngestionSource` ABC (`backend/app/plugins/base.py`). Registered via plugin registry (`backend/app/plugins/registry.py`). Sources: `github` (default), `claude_code`, `blog`, `stackoverflow`, `devblog`, `hackernews`.

### Database

PostgreSQL via async SQLAlchemy + asyncpg. Neon in production, local PostgreSQL in dev. Migrations managed by Alembic (`backend/alembic/`). Connection config in `backend/app/db.py` — prefers `NEON_DATABASE_URL` over `DATABASE_URL`.

### Authentication (Neon Auth + BFF proxy)

1. Frontend uses `@neondatabase/auth` with GitHub OAuth
2. Next.js BFF proxy (`frontend/src/app/api/proxy/[...path]/route.ts`) calls `/api/auth/sync` to upsert user, then issues a service JWT signed with `SERVICE_JWT_SECRET`
3. Backend validates service JWT via `get_current_user` dependency (`backend/app/core/auth.py`)

### LLM integration

All LLM calls go through `backend/app/core/llm.py` using litellm (provider-agnostic). Default model: `gemini/gemini-2.5-flash`. Langfuse tracing is optional (`LANGFUSE_ENABLED=true`). Key Gemini/litellm quirks are handled in `backend/app/core/agent.py`: `tool_choice="required"` on first turn, `thinking` must be disabled for multi-turn function calling, retry on `malformed_function_call`.

## Key File Map

| To change... | Modify... |
|---|---|
| Pipeline stages/flow | `backend/app/synthesis/pipeline.py` |
| Soul document prompts | `backend/app/synthesis/chief.py` |
| Memory assembly logic | `backend/app/synthesis/memory_assembler.py` |
| System prompt structure | `backend/app/synthesis/spirit.py` |
| Add/modify an explorer | `backend/app/synthesis/explorers/<source>_explorer.py` |
| Explorer base tools | `backend/app/synthesis/explorers/base.py` |
| Agent loop / LLM calls | `backend/app/core/agent.py` |
| LLM provider config | `backend/app/core/llm.py` |
| Add an ingestion source | `backend/app/plugins/sources/<source>.py` + register in `registry.py` |
| Chat behavior/tools | `backend/app/routes/chat.py` |
| Mini creation endpoint | `backend/app/routes/minis.py` |
| Database models | `backend/app/models/` (`mini.py`, `user.py`, `knowledge.py`, etc.) |
| Database connection | `backend/app/db.py` |
| App config / env vars | `backend/app/core/config.py` |
| Auth flow (backend) | `backend/app/core/auth.py`, `backend/app/routes/auth.py` |
| Auth flow (frontend) | `frontend/src/lib/auth.ts`, `frontend/src/app/api/proxy/[...path]/route.ts` |
| Frontend pages | `frontend/src/app/<route>/page.tsx` |
| API client functions | `frontend/src/lib/api.ts` |

## Environment Setup

```bash
# 1. Install mise, then install toolchain
curl https://mise.run | sh && mise install

# 2. Backend
cd backend && cp .env.example .env
# Edit .env — set GEMINI_API_KEY and GITHUB_TOKEN at minimum
# Set DATABASE_URL to a PostgreSQL connection string
uv sync

# 3. Run migrations
cd backend && uv run alembic upgrade head

# 4. Frontend
cd frontend && pnpm install
# Create .env.local with AUTH_GITHUB_ID, AUTH_GITHUB_SECRET, AUTH_SECRET,
# BACKEND_URL=http://localhost:8000, SERVICE_JWT_SECRET (must match backend)

# 5. Run
mise run dev
```

## Required Environment Variables

**Backend** (`backend/.env`):
- `GEMINI_API_KEY` — Google Gemini API key (used by litellm)
- `GITHUB_TOKEN` — GitHub PAT for profile ingestion
- `DATABASE_URL` — PostgreSQL connection (`postgresql+asyncpg://...`)
- `JWT_SECRET`, `SERVICE_JWT_SECRET` — Auth secrets (defaults provided for dev)

**Frontend** (`frontend/.env.local`):
- `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET` — GitHub OAuth app credentials
- `AUTH_SECRET` — Neon Auth secret (generate with `npx auth secret`)
- `BACKEND_URL` — Backend URL (`http://localhost:8000` in dev)
- `SERVICE_JWT_SECRET` — Must match backend's value

## Claude Code Commands

- `/mini-review <username>` — Get a code review from a developer mini
- `/mini-chat <username>` — Chat with a developer mini
- `/mini-create <username>` — Create a new mini from a GitHub username
- `/mini-team <action> [usernames...]` — Assemble a team of minis for review/discuss/brainstorm

## API

Backend runs at `http://localhost:8000`. Swagger docs available at `/docs` in development.

- `POST /api/minis` — Create mini `{"username": "torvalds"}`
- `GET /api/minis` — List all minis
- `GET /api/minis/{username}` — Get mini details
- `POST /api/minis/{username}/chat` — Chat with mini (SSE)
- `GET /api/minis/{id}/progress` — Stream pipeline progress (SSE)
- `GET /api/health` — Health check
