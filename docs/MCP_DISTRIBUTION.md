# MCP Distribution Contract

This is the developer reference for using Minis inside coding sessions through
Claude Code or any MCP client.

## Auth

The supported non-browser-client auth path is GitHub device flow:

```bash
cd mcp-server
uv run minis-mcp auth login
```

The MCP client asks the backend for the configured GitHub OAuth client ID, uses
GitHub's device-code flow, exchanges the approved GitHub token at
`POST /api/auth/github-device/exchange`, and stores the resulting Minis bearer
token at `~/.config/minis/mcp-token`.

`MINIS_AUTH_TOKEN` overrides the token file. `MINIS_AUTH_TOKEN_FILE` overrides
the token-file path.

Backend requirement: set `GITHUB_DEVICE_CLIENT_ID` to a GitHub OAuth App client
ID with device flow enabled.

## Tool Contract

Tools must not fabricate review or framework signal when the mini does not have
usable evidence.

- `get_decision_frameworks` returns `frameworks_available=false`,
  `mode=gated`, and an `unavailable_reason` when no framework evidence exists.
- `predict_review` returns `prediction_available=false`, `mode=gated`, and no
  blockers/questions when the backend predictor is disabled or unavailable.
- `advise_coding_changes` derives its change plan only from an available
  `predict_review` result. If prediction is gated, guidance is also gated.

## Claude Code Setup

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

For local development, set `MINIS_BACKEND_URL=http://localhost:8000`.

## Coding Session Flow

1. Call `get_decision_frameworks` for the reviewer mini.
2. Call `predict_review` with title, description, changed files, repo name, and
   diff summary.
3. Call `advise_coding_changes` when you want a change checklist derived from
   the same review-prediction artifact.
4. If any tool returns `mode=gated`, stop and surface the unavailable reason
   rather than replacing it with generic coding advice.
