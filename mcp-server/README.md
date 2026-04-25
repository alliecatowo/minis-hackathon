# Minis MCP Server

MCP server that wraps the Minis API, letting coding agents use a mini inside Claude Code, Claude Desktop, or any MCP client.

## Tools

| Tool | Description |
|------|-------------|
| `list_sources` | List the ingestion sources currently exposed by the backend |
| `create_mini` | Create or regenerate a mini from a GitHub username |
| `list_minis` | List public minis, or your own minis with auth |
| `get_mini` | Get the current mini profile by UUID or username |
| `get_mini_status` | Follow pipeline progress events until completion |
| `chat_with_mini` | Send a message to a mini and collect the streamed reply |
| `get_mini_graph` | Fetch the mini's knowledge graph and principles payload |
| `predict_review` | Ask what a mini would likely block on for a proposed change before review |
| `get_decision_frameworks` | Fetch learned decision frameworks with explicit unavailable gating |
| `advise_coding_changes` | Turn an available review prediction into a coding-session change plan |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- A Minis backend URL. The default is `https://minis.fly.dev`; set `MINIS_BACKEND_URL` for staging or local development.
- For authenticated/private minis: a token from `uv run minis-mcp auth login`, or `MINIS_AUTH_TOKEN`.

## Authenticate

The main non-browser client path is GitHub device auth. It does not require a localhost callback.

```bash
cd mcp-server
uv run minis-mcp auth login
```

The command prints a GitHub verification URL and one-time code, exchanges the approved GitHub device token with the Minis backend, then stores a user-scoped Minis bearer token at:

```text
~/.config/minis/mcp-token
```

Override the token file with `MINIS_AUTH_TOKEN_FILE`. `MINIS_AUTH_TOKEN` still works and takes precedence.

## Running standalone

```bash
cd mcp-server
uv run minis-mcp
```

## Claude Code configuration

Add to `.claude/settings.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "minis": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp-server", "minis-mcp"],
      "env": {
        "MINIS_BACKEND_URL": "https://minis.fly.dev"
      }
    }
  }
}
```

## Claude Code pre-review workflow

Use `predict_review` when you want a quick "what would this reviewer likely block on?" pass before sending code for human review. Pass at least one of `title`, `description`, `diff_summary`, or `changed_files`.

Example prompt:

```text
Use the minis MCP server `predict_review` tool for reviewer `alliecatowo`.
Title: "Refactor auth retries"
Description: "Touches token refresh and worker retry behavior."
Changed files: ["backend/app/core/auth.py", "backend/app/worker.py"]
Diff summary: "Adds retry logic and reshapes the auth error path."
Tell me the likely blockers first, then the open questions.
```

For code-writing assistance, use `advise_coding_changes` on the same diff context. If the mini has no usable review evidence or the backend predictor is disabled, the tool returns `guidance_available=false` with `mode=gated` and no fallback advice.

## Claude Desktop configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "minis": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp-server", "minis-mcp"],
      "env": {
        "MINIS_BACKEND_URL": "https://minis.fly.dev"
      }
    }
  }
}
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIS_BACKEND_URL` | `https://minis.fly.dev` | URL of the Minis FastAPI backend |
| `MINIS_AUTH_TOKEN` | unset | Optional bearer token forwarded to authenticated backend routes; overrides token file |
| `MINIS_AUTH_TOKEN_FILE` | `~/.config/minis/mcp-token` | File written by `auth login` and read by the MCP server |

## Backend configuration

Device auth requires the backend to set `GITHUB_DEVICE_CLIENT_ID` to a GitHub OAuth App client ID that supports device flow. The MCP client retrieves this public client ID from `/api/auth/github-device/config`.
