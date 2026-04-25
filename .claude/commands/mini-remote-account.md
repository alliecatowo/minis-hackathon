---
allowed-tools: Bash(python:*), Bash(uv:*), Bash(curl:*)
description: Use hosted account minis through authenticated API/MCP setup. Usage: /mini-remote-account <check|list|chat|review> [...]
---

## Your Task

The user wants remote account mode for hosted Minis. The arguments provided are: $ARGUMENTS

Remote account mode must be authenticated. Do not fall back to public minis or local demo mode when auth is missing.

Follow these steps exactly:

1. Parse the action. Valid actions are `check`, `list`, `chat`, and `review`. If omitted, run `check`.

2. Always check setup first:

   ```bash
   python scripts/minis_claude_plugin_modes.py remote-check --json
   ```

   If the JSON says `"available": false`, stop and show the setup instructions. The preferred setup is `cd mcp-server && uv run minis-mcp auth login`, which writes `~/.config/minis/mcp-token`. Env alternatives: `MINIS_TOKEN`, `MINIS_AUTH_TOKEN`, or `MINIS_AUTH_TOKEN_FILE`. Optional backend env: `MINIS_API_BASE` or `MINIS_BACKEND_URL`.

3. For `list`, run:

   ```bash
   python scripts/minis_claude_plugin_modes.py remote-list
   ```

4. For `chat`, parse `<username> <message...>` and run the hosted API client:

   ```bash
   uv run python backend/cli.py chat <username> "<message>"
   ```

5. For `review`, parse `<username>` and optional `--base`, `--title`, `--author-model`, and `--context` args. Then run:

   ```bash
   uv run python backend/cli.py pre-review <username> --base origin/main --title "<title>"
   ```

   Preserve any explicit args the user provided. If no title is provided, use a concise title derived from the current task.

6. If the user specifically asks for MCP configuration, show the `MINIS_BACKEND_URL` env shape from the `remote-check` output and point them to `mcp-server/README.md`. Do not invent a token or claim the MCP server is authenticated unless setup check passed.
