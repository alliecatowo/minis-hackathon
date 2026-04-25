---
name: minis
description: |
  Minis integration skill for interacting with AI personality clones built from GitHub profiles.
  This skill should be used when a user wants to chat with, create, or get reviews from developer
  minis (AI personality clones). It provides knowledge of the Minis API and how to interact with
  minis in the terminal.
allowed-tools:
  - Bash(curl:*)
  - Bash(git diff:*)
  - Bash(git status:*)
  - Bash(git log:*)
---

# Minis - Developer Personality Clones in Your Terminal

Minis creates AI personality clones from GitHub profiles. Each mini captures a developer's
coding values, communication style, and personality patterns from their public GitHub activity.

## Minis API Reference

The Minis backend runs at `http://localhost:8000`. All endpoints are under `/api/`.

### Create a Mini

```
POST http://localhost:8000/api/minis
Content-Type: application/json
{"username": "<github_username>"}
```

Returns 202 with a `MiniSummary`. The pipeline runs in the background. Status values:
`processing`, `ready`, `failed`, `pending`.

### List All Minis

```
GET http://localhost:8000/api/minis
```

Returns an array of `MiniSummary` objects.

### Get Mini Details

```
GET http://localhost:8000/api/minis/<username>
```

Returns a `MiniDetail` with fields: `username`, `display_name`, `avatar_url`, `bio`,
`spirit_content`, `system_prompt`, `values_json`, `metadata_json`, `status`.

### Chat with a Mini

```
POST http://localhost:8000/api/minis/<username>/chat
Content-Type: application/json
{"message": "...", "history": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

Returns a Server-Sent Events (SSE) stream with `event: chunk` containing text deltas
and `event: done` when complete.

### Pipeline Status Stream

```
GET http://localhost:8000/api/minis/<username>/status
```

SSE stream of pipeline progress events during mini creation.

### Health Check

```
GET http://localhost:8000/api/health
```

## Plugin Modes

### Local/demo mode

Use local/demo mode when the user wants to make their own mini from the current repository without hosted Minis:

```bash
python scripts/minis_claude_plugin_modes.py local-demo --force
```

Claude Code command: `/mini-local-demo [display_name]`

This mode is grounded only in local git metadata and allowlisted repository docs. It must not claim hosted account evidence or private review history.

### Remote account mode

Use remote account mode when the user wants minis from their hosted account via API or MCP auth:

```bash
python scripts/minis_claude_plugin_modes.py remote-check --json
python scripts/minis_claude_plugin_modes.py remote-list
```

Claude Code command: `/mini-remote-account <check|list|chat|review> [...]`

Remote account mode requires `MINIS_TOKEN` or `MINIS_AUTH_TOKEN`. If auth is missing, stop with setup instructions; do not fall back to public minis or local demo mode.

## Working with Minis

### Fetching Mini Personality

To use a mini's personality for code review or conversation, first fetch the mini details:

```bash
curl -s http://localhost:8000/api/minis/<username> | jq .
```

The `system_prompt` field contains the full personality prompt. The `values_json` field
contains structured engineering values, communication style, and personality patterns.

### Collecting Chat Responses from SSE

The chat endpoint returns SSE. To collect the full response:

```bash
curl -s -N -X POST http://localhost:8000/api/minis/<username>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "...", "history": []}' | \
  grep '^data: ' | sed 's/^data: //' | grep -v '^$' | tr -d '\n'
```

### Error Handling

- **404**: Mini not found. Suggest creating it with `/mini-create`.
- **409**: Mini is not ready yet (still processing). Check status.
- **Connection refused**: Backend is not running. Start with `mise run dev-backend`
  or `cd backend && uv run uvicorn app.main:app --reload --port 8000`.
