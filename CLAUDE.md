# Minis - Developer Personality Clones

AI personality clones built from GitHub profiles. Your favorite developers, in your terminal.

## Project Structure

- `backend/` - FastAPI backend (Python 3.13, uv)
- `frontend/` - Next.js frontend (pnpm)
- `mcp-server/` - MCP server for Claude Code tool integration
- `github-app/` - GitHub App for PR review by minis
- `.claude/` - Claude Code skills, commands, and agents

## Architecture

### Pipeline (5 stages)

Creating a mini runs a 5-stage pipeline (`backend/app/synthesis/pipeline.py`):

1. **FETCH** -- Ingestion sources pull raw data (GitHub API, blog scraping, etc.)
2. **EXPLORE** -- Per-source Explorer agents (ReAct loop with tools) analyze evidence in parallel, producing `ExplorerReport`s with personality findings, memories, quotes, knowledge graph nodes, and principles
3. **ASSEMBLE** -- Memory assembler merges explorer reports into a structured memory document (facts, opinions, quotes organized by category) and extracts roles/skills/traits via LLM
4. **SYNTHESIZE** -- Chief synthesizer agent cross-references all explorer reports to craft the soul document (personality, style, values, anti-values)
5. **SAVE** -- Persists soul document, memory document, system prompt, and structured data to the Mini record

### Key concepts

- **Soul document** (`spirit_content`): Defines WHO the person is -- personality, communication style, values, anti-values. Written as instructions, not descriptions. Produced by the chief synthesizer.
- **Memory document** (`memory_content`): Defines WHAT the person knows -- projects, expertise, opinions, behavioral quotes. Produced by the memory assembler.
- **System prompt** (`system_prompt`): Wraps soul + memory into a four-pillar prompt (Personality, Style, Values, Knowledge) with behavioral guidelines. Built by `spirit.build_system_prompt()`.
- **Knowledge graph** (`knowledge_graph_json`): Structured nodes (skills, projects, patterns) and edges (relationships) extracted by explorers.
- **Principles matrix** (`principles_json`): Decision rules (trigger -> action -> value) extracted by explorers.

### Explorer system

Explorers are ReAct agents that analyze evidence from a specific source. Each explorer:
- Extends `Explorer` ABC (`backend/app/synthesis/explorers/base.py`)
- Implements `system_prompt()` and `user_prompt()`
- Runs via `run_agent()` with tools: `save_memory`, `save_finding`, `save_quote`, `analyze_deeper`, `save_context_evidence`, `save_knowledge_node`, `save_knowledge_edge`, `save_principle`, `finish`
- Self-registers via `register_explorer()` in its module

Current explorers: `github`, `claude_code`, `blog`, `hackernews`, `stackoverflow`, `devblog`

### Agent system

The agent framework (`backend/app/core/agent.py`) provides:

- **`AgentTool`** dataclass: `name`, `description`, `parameters` (JSON Schema), `handler` (async callable)
- **`run_agent()`**: Non-streaming ReAct loop. Calls LLM with tools, executes tool calls, repeats until text response or max turns. Forces `tool_choice="required"` on first turn.
- **`run_agent_streaming()`**: Streaming variant for chat. Yields `AgentEvent`s (`tool_call`, `tool_result`, `chunk`, `done`, `error`). Used by the chat endpoint.
- **Tool handler pattern**: Define async functions, wrap in `AgentTool`, pass to `run_agent()`. The agent calls tools by name; handlers receive kwargs from the LLM's function call arguments.

### Ingestion sources

Ingestion sources implement `IngestionSource` ABC (`backend/app/plugins/base.py`). They fetch raw data and format evidence text. Registered via the plugin registry (`backend/app/plugins/registry.py`).

Sources: `github` (default), `claude_code`, `blog`, `stackoverflow`, `devblog`, `hackernews`

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
| Add an ingestion source | `backend/app/plugins/sources/<source>.py` + register in `registry.py` |
| Chat behavior/tools | `backend/app/routes/chat.py` |
| Mini creation endpoint | `backend/app/routes/minis.py` |
| Database models | `backend/app/models/mini.py`, `backend/app/models/knowledge.py` |
| App config / env vars | `backend/app/core/config.py` |
| Frontend pages | `frontend/src/app/<route>/page.tsx` |
| API client functions | `frontend/src/lib/api.ts` |

## Environment Setup

```bash
# 1. Install mise (manages pnpm, uv, node, python)
curl https://mise.run | sh

# 2. Install toolchain
mise install

# 3. Backend setup
cd backend
cp .env.example .env
# Edit .env -- set GEMINI_API_KEY and GITHUB_TOKEN at minimum
uv sync

# 4. Frontend setup
cd frontend
pnpm install

# 5. Run dev servers
mise run dev           # Both backend (:8000) and frontend (:3000)
mise run dev-backend   # Backend only
mise run dev-frontend  # Frontend only
```

The SQLite database auto-creates on first run. Delete `minis.db` if you change model schemas.

## Development

```bash
mise run dev           # Run both backend and frontend
mise run dev-backend   # Run FastAPI backend on :8000
mise run dev-frontend  # Run Next.js frontend on :3000
```

### Common workflows

**Create a mini** (via API):
```bash
curl -X POST http://localhost:8000/api/minis \
  -H "Content-Type: application/json" \
  -d '{"username": "torvalds", "sources": ["github"]}'
```
Then watch the pipeline progress via SSE at `GET /api/minis/{id}/progress`.

**Chat with a mini** (via API):
```bash
curl -X POST http://localhost:8000/api/minis/torvalds/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What do you think of Rust?"}'
```
Response streams via SSE with `chunk`, `tool_call`, `tool_result`, and `done` events.

**Add a new explorer**:
1. Create `backend/app/synthesis/explorers/myexplorer_explorer.py`
2. Subclass `Explorer`, set `source_name`, implement `system_prompt()` and `user_prompt()`
3. Call `register_explorer("mysource", MyExplorer)` at module level
4. Import the module in `backend/app/synthesis/pipeline.py` to trigger registration

**Add a new ingestion source**:
1. Create `backend/app/plugins/sources/mysource.py`
2. Subclass `IngestionSource`, implement `fetch()` returning `IngestionResult`
3. Register in `backend/app/plugins/registry.py`

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
- `GET /api/minis/{id}/progress` - Stream pipeline progress (SSE)
