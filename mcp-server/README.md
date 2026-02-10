# Minis MCP Server

MCP server that wraps the Minis API, letting you create and chat with AI personality clones of GitHub developers from any MCP client (Claude Desktop, Claude Code, etc).

## Tools

| Tool | Description |
|------|-------------|
| `create_mini` | Create an AI personality clone from a GitHub username |
| `list_minis` | List all available minis |
| `get_mini` | Get details about a specific mini (spirit document, values, personality) |
| `get_mini_status` | Check pipeline creation status (SSE progress) |
| `chat_with_mini` | Send a message to a mini and get a response |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- Minis backend running at `http://localhost:8000` (or set `MINIS_BACKEND_URL`)

## Running standalone

```bash
cd mcp-server
uv run fastmcp run main.py
```

## Claude Code configuration

Add to `.claude/settings.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "minis": {
      "command": "uv",
      "args": ["run", "--directory", "/home/Allie/develop/minis-hackathon/mcp-server", "fastmcp", "run", "main.py"],
      "env": {
        "MINIS_BACKEND_URL": "http://localhost:8000"
      }
    }
  }
}
```

## Claude Desktop configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "minis": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp-server", "fastmcp", "run", "main.py"],
      "env": {
        "MINIS_BACKEND_URL": "http://localhost:8000"
      }
    }
  }
}
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIS_BACKEND_URL` | `http://localhost:8000` | URL of the Minis FastAPI backend |
