# Minis

**Clone any developer's mind.**

AI personality clones built from GitHub profiles. Enter a username, we analyze their commits, PRs, reviews, and blog posts, then create an AI that thinks, writes, and argues like them.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white) ![Next.js](https://img.shields.io/badge/Next.js-15-000000?style=flat&logo=next.js&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white) ![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat&logo=typescript&logoColor=white) ![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?style=flat&logo=tailwindcss&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white) ![litellm](https://img.shields.io/badge/litellm-multi--provider-orange?style=flat) ![Langfuse](https://img.shields.io/badge/Langfuse-observability-blueviolet?style=flat) ![License](https://img.shields.io/badge/License-MIT-green?style=flat)

## What is Minis?

Every developer leaves fingerprints across the internet -- commit messages that reveal how they think, code reviews that show what they value, blog posts that capture their philosophy, Stack Overflow answers that expose their expertise. Minis captures all of it. An agentic analysis pipeline deploys autonomous explorer agents across multiple data sources, mining personality signals that a single API call would miss. The result is an engram: a rich personality model that powers an AI clone capable of reviewing your code, debating architecture decisions, or mentoring you -- all in the authentic voice of the developer it was built from.

## How it Works

1. **Enter a Username** -- Point at any GitHub profile.
2. **We Analyze Everything** -- Agentic explorer agents mine personality signals from GitHub commits, PRs, code reviews, Stack Overflow, Hacker News, blogs, and more.
3. **Chat with Their Clone** -- An AI that captures their coding philosophy, communication style, and technical opinions.

## Features

**Multi-Source Analysis** -- GitHub, Stack Overflow, Hacker News, dev blogs, RSS feeds. No single source tells the whole story.

**Agentic Explorer Pipeline** -- Per-source ReAct agents with tool use that autonomously discover and analyze personality signals. Each explorer decides what to look at and how deep to go.

**Context-Aware Communication** -- Minis adapt their style based on conversation context. Code review mode is different from mentoring mode is different from brainstorming mode.

**Team Collaboration** -- Assemble teams of minis for code reviews, brainstorming sessions, and technical discussions. Get Linus and DHH to argue about your architecture.

**MCP Server** -- Use minis as tools in Claude Code via Model Context Protocol. Your minis, inside your IDE.

**Claude Code Integration** -- Slash commands for chat, review, create, and team operations. No context switching.

**Bring Your Own Key (BYOK)** -- Use your own LLM API key. Gemini, OpenAI, Anthropic, and anything else litellm supports.

**GitHub App** -- Automated PR reviews by developer minis. Install it, pick a mini, and every PR gets reviewed in their style.

**Developer Radar** -- Visualize skills, traits, and engineering values with radar charts. See what a developer cares about at a glance.

**Organizations** -- Share minis and collaborate within teams. Build a shared roster of developer clones.

## Architecture

```
GitHub Username
      |
      v
+-------------------+
|  Explorer Agents   | <-- ReAct loop with tool use
|  (per source)      |
+-------------------+
| GitHub Explorer    | -> commits, PRs, reviews, issues
| SO Explorer        | -> answers, questions, tags
| HN Explorer        | -> posts, comments
| Blog Explorer      | -> RSS/Atom feed analysis
| DevBlog Explorer   | -> dev.to articles
| Website Explorer   | -> personal/project site pages
| Claude Explorer    | -> conversation transcripts
+---------+---------+
          |
          v
+-------------------+
| Memory Assembler   | -> merge + deduplicate findings
+---------+---------+
          |
          v
+-------------------+
| Chief Synthesizer  | -> generate engram (personality model)
+---------+---------+
          |
          v
    Mini (Engram)
    +-- Bio, roles, skills, traits
    +-- Communication patterns
    +-- Engineering values (radar)
    +-- Context-specific behaviors
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

Five tools available via Model Context Protocol:

| Tool | Description |
|------|-------------|
| `create_mini` | Create a new mini from a GitHub username |
| `chat_with_mini` | Send a message and get a response |
| `get_mini` | Retrieve mini details |
| `list_minis` | List all available minis |
| `search_minis` | Search minis by keyword |

```bash
# Start the MCP server
cd mcp-server && uv run minis-mcp
```

## Live Demo

**[https://minis.dev](https://minis.dev)**

## Deployment

[![Deploy to Fly.io + Neon + Vercel](https://img.shields.io/badge/Deploy%20Your%20Own-Fly.io%20%2B%20Neon%20%2B%20Vercel-purple?style=for-the-badge)](https://github.com/alliecatowo/minis-hackathon/blob/main/DEPLOY.md)

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

- **Frontend**: `NEXT_PUBLIC_API_URL`
- **Backend**: `GEMINI_API_KEY`, `GITHUB_TOKEN`, `DEFAULT_LLM_MODEL`, `DATABASE_URL` (PostgreSQL connection string), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`

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
| Backend | FastAPI, SQLAlchemy, PostgreSQL (Neon) |
| LLM | litellm (Gemini, OpenAI, Anthropic, etc.) |
| Observability | Langfuse (LLM tracing and analytics) |
| Auth | GitHub OAuth |
| Deployment | Vercel (frontend), Fly.io (backend) |
| Tooling | mise, pnpm, uv |

## License

[MIT](LICENSE)
