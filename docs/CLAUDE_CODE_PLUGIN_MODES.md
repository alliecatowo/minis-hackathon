# Claude Code Plugin Modes

Minis has two Claude Code plugin modes. They are intentionally separate so demos do not pretend to have hosted account evidence.

## Local/demo Mode

Use this when you want a runnable demo mini from the current repository with no Minis backend.

```bash
python scripts/minis_claude_plugin_modes.py local-demo --force
```

This writes:

- `.claude/agents/<name>-local-mini.md`
- `.claude/minis/<name>-local-mini.evidence.json`

The generated agent is grounded only in local git metadata and allowlisted docs (`README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/PROGRAM.md`, `docs/REVIEW_INTELLIGENCE.md`). It must say unavailable for hosted account evidence or real private review history.

Claude Code command:

```text
/mini-local-demo [display_name]
```

## Remote Account Mode

Use this when you want hosted account minis through authenticated API or MCP.

```bash
export MINIS_TOKEN=...
export MINIS_API_BASE=https://minis-api.fly.dev/api
python scripts/minis_claude_plugin_modes.py remote-check
python scripts/minis_claude_plugin_modes.py remote-list
```

For MCP clients, pass the same auth into the MCP server:

```json
{
  "mcpServers": {
    "minis": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp-server", "minis-mcp"],
      "env": {
        "MINIS_BACKEND_URL": "https://minis-api.fly.dev",
        "MINIS_AUTH_TOKEN": "<token>"
      }
    }
  }
}
```

Claude Code command:

```text
/mini-remote-account <check|list|chat|review> [...]
```

If auth is missing, remote mode is gated with setup instructions. It does not fall back to public minis or local demo mode.

## Smoke Tests

```bash
python -m unittest discover -s scripts -p 'test_minis_claude_plugin_modes.py'
```
