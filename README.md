# Minis

**Clone any developer's mind.**

AI personality clones built from GitHub profiles. Enter a username, we analyze their commits, PRs, reviews, and blog posts, then create an AI that thinks, writes, and argues like them.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white) ![Next.js](https://img.shields.io/badge/Next.js-15-000000?style=flat&logo=next.js&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white) ![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat&logo=typescript&logoColor=white) ![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?style=flat&logo=tailwindcss&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white) ![PydanticAI](https://img.shields.io/badge/PydanticAI-multi--provider-blue?style=flat) ![Tests](https://img.shields.io/badge/Tests-805+-green?style=flat) ![Coverage](https://img.shields.io/badge/Coverage-70%25+-green?style=flat) ![License](https://img.shields.io/badge/License-MIT-green?style=flat)

## What is Minis?

Every developer leaves fingerprints across the internet -- commit messages that reveal how they think, code reviews that show what they value, blog posts that capture their philosophy, Stack Overflow answers that expose their expertise. Minis captures all of it. An agentic analysis pipeline deploys autonomous explorer agents across multiple data sources, mining personality signals that a single API call would miss. The result is an engram: a rich personality model that powers an AI clone capable of reviewing your code, debating architecture decisions, or mentoring you -- all in the authentic voice of the developer it was built from.

## How it Works

1. **FETCH** -- Ingest data from multiple sources (GitHub, Stack Overflow, blogs, Hacker News, etc.)
2. **EXPLORE** -- Per-source PydanticAI agents autonomously analyze evidence in parallel using a tool-based ReAct loop
3. **SYNTHESIZE** -- Chief synthesizer agent crafts a soul document that captures personality, philosophy, and values
4. **Chat** -- Interact with the mini in its authentic voice, getting code reviews, architectural advice, or mentoring

## Features

**Multi-Source Analysis** -- GitHub, Stack Overflow, Hacker News, dev blogs, RSS feeds. No single source tells the whole story.

**Agentic Explorer Pipeline** -- Per-source PydanticAI agents with tool use that autonomously discover and analyze personality signals. Each explorer decides what to look at and how deep to go.

**Model Hierarchy/Tier System** -- Different models for different tasks (Fast summarization, Standard exploration, Thinking for synthesis). Choose your provider: Gemini, Claude, or OpenAI.

**805+ Tests, 70%+ Coverage** -- Production-ready with comprehensive test coverage across pipeline stages, agents, and API endpoints.

**Context-Aware Communication** -- Minis adapt their style based on conversation context. Code review mode is different from mentoring mode is different from brainstorming mode.

**Team Collaboration** -- Assemble teams of minis for code reviews, brainstorming sessions, and technical discussions. Get Linus and DHH to argue about your architecture.

**MCP Server** -- Use minis as tools in Claude Code via Model Context Protocol. Your minis, inside your IDE.

**Claude Code Integration** -- Slash commands for chat, review, create, and team operations. No context switching.

**Bring Your Own Key (BYOK)** -- Use your own LLM API key. Gemini, OpenAI, Anthropic, and more—provider-agnostic via PydanticAI.

**GitHub App** -- Automated PR reviews by developer minis. Install it, pick a mini, and every PR gets reviewed in their style.

**Developer Radar** -- Visualize skills, traits, and engineering values with radar charts. See what a developer cares about at a glance.

**Organizations** -- Share minis and collaborate within teams. Build a shared roster of developer clones.

## Architecture

```
GitHub Username / Input
      |
      v
┌─────────────────────────────────────┐
│         FETCH STAGE                 │
│  Ingest data from all sources       │
│  Store as Evidence DB records       │
└──────────┬──────────────────────────┘
           |
           v
┌─────────────────────────────────────┐
│         EXPLORE STAGE               │
│  Parallel PydanticAI agents         │
│  Per-source explorer agents run     │
│  ReAct loops with DB-backed tools   │
│  Persist findings to database       │
├─────────────────────────────────────┤
│ • GitHub Explorer                   │
│ • Stack Overflow Explorer           │
│ • Hacker News Explorer              │
│ • Blog Explorer                     │
│ • DevBlog Explorer                  │
│ • Website Explorer                  │
│ • Claude Code Explorer              │
└──────────┬──────────────────────────┘
           |
           v
┌─────────────────────────────────────┐
│       SYNTHESIZE STAGE              │
│  Chief synthesizer reads DB         │
│  Crafts soul document               │
│  Saves all structured data          │
└──────────┬──────────────────────────┘
           |
           v
    Mini (Complete Profile)
    ├── Soul Document (personality)
    ├── Memory Document (knowledge)
    ├── System Prompt (4-pillar)
    ├── Knowledge Graph
    └── Principles Matrix
```

## Quick Start

```bash
# Prerequisites: mise (or node 22 + python 3.13 + pnpm + uv)
git clone https://github.com/minis-dev/minis.git
cd minis
mise install

# Set up environment
cp backend/.env.example backend/.env
# Add your GEMINI_API_KEY to backend/.env

# Run everything
mise run dev
```

Open [http://localhost:3000](http://localhost:3000) and enter a GitHub username to create your first mini.

## Hosted CLI

The backend CLI talks to the hosted Minis API by default. Set `MINIS_API_BASE` to target a local or preview backend, and set `MINIS_TOKEN` for authenticated routes such as creating, deleting, listing your own minis, or viewing owner-only agreement metrics.
It does not read or write a local SQLite minis database.

```bash
# Defaults to https://minis-api.fly.dev/api
export MINIS_API_BASE=http://localhost:8000/api
export MINIS_TOKEN=...

uv run python backend/cli.py list
uv run python backend/cli.py list --mine
uv run python backend/cli.py create antirez
uv run python backend/cli.py chat antirez "What would you block on in this design?"
```

Use the backend CLI to ask what a mini would likely block on before you request human review. The command compares your current git working tree against a base ref, sends the changed files plus a diff summary to the existing review-prediction backend, and prints the likely blockers.

```bash
uv run python backend/cli.py pre-review alliecatowo \
  --base origin/main \
  --title "Refactor auth token handling" \
  --author-model senior_peer
```

Pass `--context hotfix|normal|exploratory|incident` when the delivery context matters. If a mini or review/chat path is gated, the CLI prints the unavailable state instead of synthesizing fallback output.

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/minis` | Create a mini from a GitHub username |
| `GET` | `/api/minis` | List all minis |
| `GET` | `/api/minis/{username}` | Get mini details and engram |
| `POST` | `/api/minis/{id}/chat` | Chat with a mini (SSE streaming) |
| `GET` | `/api/minis/{id}/contexts` | List available contexts |
| `POST` | `/api/teams` | Create a team |
| `GET` | `/api/teams` | List teams |
| `POST` | `/api/orgs` | Create an organization |
| `GET` | `/api/sources` | List available data sources |

## Claude Code Integration

Two plugin modes are available:

```bash
# Local/demo: generate a repo-grounded mini with no hosted dependency
/mini-local-demo

# Remote account: use hosted minis through authenticated API/MCP setup
/mini-remote-account check
```

See `docs/CLAUDE_CODE_PLUGIN_MODES.md` for setup and smoke tests.

```bash
# Chat with a mini
/mini-chat torvalds "What's your opinion on Rust?"

# Get a code review
/mini-review dhh src/controllers/

# Create a mini
/mini-create antirez

# Team brainstorm
/mini-team brainstorm torvalds dhh antirez
```

## MCP Server

Current Minis MCP tools:

| Tool | Description |
|------|-------------|
| `list_sources` | List ingestion sources exposed by the backend |
| `create_mini` | Create or regenerate a mini from a GitHub username |
| `list_minis` | List public minis, or your own minis with auth |
| `get_mini` | Retrieve a mini by UUID or username |
| `get_mini_status` | Stream pipeline progress events |
| `chat_with_mini` | Send a message and collect the streamed reply |
| `get_mini_graph` | Retrieve the mini's knowledge graph and principles |

```bash
# Start the MCP server
cd mcp-server && uv run minis-mcp
```

## Live Demo

**[https://my-mini.me](https://my-mini.me)**

## Deployment

[![Deploy to Fly.io + Neon + Vercel](https://img.shields.io/badge/Deploy%20Your%20Own-Fly.io%20%2B%20Neon%20%2B%20Vercel-purple?style=for-the-badge)](https://github.com/alliecatowo/minis-ai/blob/main/DEPLOY.md)

One-click deployment with:
- **Neon** — Serverless Postgres with automatic branching per PR
- **Fly.io** — Backend API with review apps for every pull request  
- **Vercel** — Frontend with preview deployments wired to preview backends

**Manual deployment:**

```bash
# Frontend
cd frontend && vercel --prod

# Backend  
cd backend && fly deploy
```

Environment variables needed:

- **Frontend**: `BACKEND_URL`, `SERVICE_JWT_SECRET`, Auth.js/Neon Auth credentials (see `.env.production.example`)
- **Backend**: `GOOGLE_API_KEY` (or `GEMINI_API_KEY`), `GITHUB_TOKEN`, `DEFAULT_PROVIDER` (`gemini` | `anthropic` | `openai`), `DATABASE_URL` (PostgreSQL), `SERVICE_JWT_SECRET`, `INTERNAL_API_SECRET`, `ENCRYPTION_KEY` for encrypted user secrets (see `.env.example`)

## CI/CD

Every pull request gets a full preview environment:

- **Neon branch** — Isolated database (`pr-42` for PR #42)
- **Fly review app** — `minis-api-pr-42.fly.dev` pointing to Neon branch
- **Vercel preview** — Auto-wired to Fly review app

Merged PRs deploy automatically to production.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 15, React 19, Tailwind CSS v4, shadcn/ui |
| Backend | FastAPI, SQLAlchemy, async PostgreSQL (Neon) |
| LLM Agents | PydanticAI (Gemini, Claude, OpenAI) |
| Testing | pytest with 805+ tests, 70%+ coverage |
| Auth | Neon Auth + BFF proxy + service JWT |
| Deployment | Vercel (frontend), Fly.io (backend), Neon (database) |
| Tooling | mise (task runner), pnpm, uv |

## License

[MIT](LICENSE)
