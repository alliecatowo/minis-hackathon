# Minis - Developer Personality Clones

AI personality clones built from GitHub profiles. Your favorite developers, in your terminal.

## Project Structure

- `backend/` - FastAPI backend (Python 3.13, uv)
- `frontend/` - Next.js frontend (pnpm)
- `mcp-server/` - MCP server for Claude Code tool integration
- `github-app/` - GitHub App for PR review by minis
- `.claude/` - Claude Code skills, commands, and agents

## Development

```bash
mise run dev           # Run both backend and frontend
mise run dev-backend   # Run FastAPI backend on :8000
mise run dev-frontend  # Run Next.js frontend on :3000
```

## Claude Code Commands

- `/mini-review <username>` - Get a code review from a developer mini
- `/mini-chat <username>` - Chat with a developer mini
- `/mini-create <username>` - Create a new mini from a GitHub username
- `/mini-team <action> [usernames...]` - Assemble a team of minis for review/discuss/brainstorm

## API

Backend runs at `http://localhost:8000`. Key endpoints:

- `POST /api/minis` - Create mini `{"username": "torvalds"}`
- `GET /api/minis` - List all minis
- `GET /api/minis/{username}` - Get mini details
- `POST /api/minis/{username}/chat` - Chat with mini (SSE)
