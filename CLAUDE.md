# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## STOP — READ THIS FIRST

**Before you make any change, read [`docs/VISION.md`](./docs/VISION.md).** It is the north-star spec. Every decision — architectural, feature-level, test-level, naming-level — is tested against it. This file below is the *how*. VISION.md is the *why*. If you only have context budget for one, read VISION.md.

Then read [`docs/PROGRAM.md`](./docs/PROGRAM.md) for execution priorities, spike protocol, and what kinds of work actually move the moat.

Summary you must never forget:

- **The product is decision-framework cloning.** Voice is the demo; predicting what the engineer would say on novel inputs is the moat.
- **5 tiers** (IC velocity → Senior focus → Team force-multiplier → Business cross-team → Enterprise knowledge retention). Every feature moves some tier forward or gets downgraded.
- **Append-only evidence, no legacy paths, file tickets liberally, Linear is source of truth.** All enforced by memory principles your orchestrator inherits.
- **Spikes are first-class deliverables.** A spike must end in a durable write-up plus follow-up tickets, not a chat-only summary.
- **For review / GitHub App / MCP work, also read [`docs/REVIEW_INTELLIGENCE.md`](./docs/REVIEW_INTELLIGENCE.md).** The product target is not generic review generation; it is predicting what this engineer would choose to say to this person in this context.
- **For framework confidence updates and the learning loop, read [`docs/FRAMEWORK_CONFIDENCE_LOOP.md`](./docs/FRAMEWORK_CONFIDENCE_LOOP.md).** This is how predictions sharpen over time through ground-truth feedback.

If you've internalized the vision, proceed to "Project Overview" below.

## Project Overview

AI personality clones ("minis") built from GitHub profiles and authorized digital exhaust. An agentic pipeline analyzes commits, PRs, reviews, code, Claude Code sessions, and more, then produces a decision-framework clone of the developer — a mini that predicts their reviews, surfaces their values, and applies their frameworks to novel inputs.

Voice/personality is the demo. Framework cloning is the product. See [`docs/VISION.md`](./docs/VISION.md).

## Recent Changes (2026-05-09)

- **Langfuse v4 upgrade & enable by default** ([docs/audits/](./docs/audits/) for details) — Langfuse tracing now enabled in dev/prod, upgraded to modern v4 API, all four pipeline stages traced.
- **mise auto-env** — `mise.toml` now auto-loads `backend/.env`, no manual `source` needed.

See audit files in `docs/audits/2026-05-09-*` for technical details.

Canonical GitHub repo for current project work is `alliecatowo/minis-ai`. Do not open PRs or attach new Linear/GitHub references to `alliecatowo/minis`, `alliecatowo/my-minis`, `minis-v2`, or the old `alliecatowo/minis-hackathon` surface unless a Linear issue explicitly says so.

## Commands

```bash
# Dev servers
mise run dev              # Both backend (:8000) and frontend (:3000)
mise run dev-backend      # Backend only
mise run dev-frontend     # Frontend only

# Testing
mise run test              # Run all backend tests
mise run test-unit         # Unit tests only (excludes integration/e2e)
mise run test-integration  # Integration tests only (requires NEON_DATABASE_URL or local Postgres)
mise run test-coverage     # Tests with HTML + terminal coverage report

# Linting & formatting
mise run lint              # Lint check (ruff)
mise run lint-fix          # Auto-fix lint issues
mise run format            # Format backend code

# Frontend
mise run typecheck         # TypeScript type check
mise run build             # Build frontend for production

# Database
mise run migrate           # Run DB migrations (alembic upgrade head)
mise run migrate-create    # Create a new migration (append -m "message")
mise run db-reset          # Stamp current state as head

# Utilities
mise run health            # Check backend health endpoint
mise run logs              # Tail backend/logs/app.log
mise run setup-hooks       # Install git hooks (Lefthook)

# One-off pytest invocations
cd backend && uv run pytest tests/test_agent.py    # Run single test file
cd backend && uv run pytest -k "test_name"         # Run test by name

# Fidelity eval (requires running backend)
cd backend && uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo,jlongster,joshwcomeau \
  --base-url http://localhost:8000 \
  --out eval-report.md

# E2E tests (requires running frontend + backend)
cd e2e && pnpm exec playwright test

# Deployment
cd frontend && vercel --prod           # Deploy frontend to Vercel
cd backend && fly deploy               # Deploy backend to Fly.io
```

## Project Structure

- `backend/` — FastAPI + SQLAlchemy + PostgreSQL (Python 3.13, uv)
- `frontend/` — Next.js 15 + Tailwind v4 + shadcn/ui (pnpm)
- `mcp-server/` — FastMCP server wrapping Minis API (13 tools)
- `github-app/` — GitHub App webhook server for PR reviews by minis
- `.claude/` — Claude Code skills, commands, and agent definitions
- `backend/app/explorer/` — Local-clone primitives: `clone_manager.py` (stable clone paths, incremental refresh) and `repo_tools.py` (safe filesystem + git read tools for repo agents). Used by the RepoAgent fan-out in `github_explorer.py` (ALLIE-373/388/389).
- `backend/eval/` — Fidelity evaluation harness: golden turns per subject, LLM-as-judge scoring, Markdown + JSON reports. Entry point: `backend/scripts/run_fidelity_eval.py` (ALLIE-382/385).
- `e2e/` — Playwright smoke tests (`smoke.spec.ts`, `create-mini.spec.ts`, `regenerate.spec.ts`) against live URLs (ALLIE-381).

Tooling is managed by mise (see `mise.toml`): pnpm, uv, node 22, python 3.13.

## Observability

**Langfuse tracing** — All LLM calls are traced to [Langfuse](https://us.cloud.langfuse.com). Enabled by default (`LANGFUSE_ENABLED=true`). Use the Langfuse MCP when debugging fidelity issues or analyzing LLM costs. Traces include all four pipeline stages (FETCH, EXPLORE, SYNTHESIZE, SAVE).

**Environment auto-load** — `mise.toml` now auto-loads `backend/.env` via `[env]._.file`. No need to manually `source` backend/.env before running mise tasks — just `mise run <task>` and env vars are available.

## Pre-commit Hooks

Install hooks once after cloning:

```bash
mise run setup-hooks
```

## Architecture

### Pipeline (3 stages)

Creating a mini runs a pipeline defined in `backend/app/synthesis/pipeline.py`:

1. **FETCH** — Ingestion sources pull raw data (GitHub API, blog scraping, etc.) and store it as `Evidence` DB records
2. **EXPLORE** — Per-source PydanticAI explorer agents run in parallel. Each agent uses the DB-backed tool suite (`tools.py`) to browse, read, and annotate evidence, persisting findings/quotes/knowledge nodes directly to the database
3. **SYNTHESIZE** — Chief synthesizer agent reads all persisted findings from DB to craft the soul document, then saves all structured data to the `Mini` record

#### Freshness semantics

- `freshness_mode="replace"` (default): before EXPLORE starts (after FETCH), wipe stale explorer synthesis rows for that mini and rebuild fresh outputs.
- Wiped tables in replace mode: `ExplorerFinding`, `ExplorerQuote`, `ExplorerNarrative`, `ExplorerProgress`, plus `ExplorerMemory` only if that model exists in the active schema.
- `freshness_mode="append"`: legacy behavior for ad-hoc additions; no pre-EXPLORE wipe.
- `Evidence` rows are never deleted by freshness handling (append-only provenance history).
- `Mini` synthesis fields (`knowledge_graph_json`, `principles_json`, `system_prompt`, `spirit_content`, `memory_content`) are overwritten together in one SAVE transaction.

### Key concepts

- **Soul document** (`spirit_content`): WHO the person is — personality, communication style, values. Written as instructions, not descriptions. Produced by the chief synthesizer.
- **Memory document** (`memory_content`): WHAT the person knows — projects, expertise, opinions, behavioral quotes. Assembled inline from explorer `ExplorerReport.memory_entries` during the SYNTHESIZE stage.
- **System prompt** (`system_prompt`): Wraps soul + memory into a four-pillar prompt (Personality, Style, Values, Knowledge). Built by `spirit.build_system_prompt()`.
- **Knowledge graph** (`knowledge_graph_json`): Structured nodes (skills, projects, patterns) and edges extracted by explorers via `save_knowledge_node` / `save_knowledge_edge` tools.
- **Principles matrix** (`principles_json`): Decision rules (trigger → action → value) extracted by explorers via `save_principle` tool.

### Agent framework

`backend/app/core/agent.py` wraps PydanticAI's `Agent` class:

- **`AgentTool`** dataclass: `name`, `description`, `parameters` (JSON Schema), `handler` (async callable). Kept for backward compatibility; converted to PydanticAI `Tool` objects (via `FunctionSchema`) at agent run time.
- **`run_agent()`**: Non-streaming loop calling `Agent.run()`. Returns `AgentResult` with `final_response`, `tool_outputs`, and `turns_used`.
- **`run_agent_streaming()`**: Streaming variant calling `Agent.run_stream_events()`, yielding `AgentEvent`s (`tool_call`, `tool_result`, `chunk`, `done`, `error`).

### Model hierarchy

`backend/app/core/models.py` defines the model tier system:

- **`ModelTier`** enum: `FAST` (compaction/summaries), `STANDARD` (explorers/chat), `THINKING` (soul synthesis), `EMBEDDING` (vectors)
- **`get_model(tier, user_override)`**: Resolves a PydanticAI model string (`"provider:model-name"`). Resolution order: user override → provider defaults → Gemini fallback.
- **`DEFAULT_PROVIDER`** env var: Selects the active provider (`gemini` / `anthropic` / `openai`). Defaults to `gemini`.
- Provider defaults are defined in `PROVIDER_DEFAULTS` — e.g. Gemini STANDARD = `google-gla:gemini-2.5-flash`, Anthropic STANDARD = `anthropic:claude-sonnet-4-6`, OpenAI STANDARD = `openai:gpt-4.1`.

### Compaction

`backend/app/core/compaction.py` applies per-provider context compaction via `create_compaction_processor()`:

- **Gemini / unknown providers**: Uses `pydantic_ai_summarization` to LLM-summarize history when it grows too large (FAST tier model, triggers at 40 messages, keeps 10).
- **Anthropic**: Returns `None` — native server-side compaction via `compact-2026-01-12` beta header.
- **OpenAI**: Returns `None` — native API compaction via `context_management.compact_threshold`.

The returned processor (or `None`) is passed as `history_processors` when constructing a PydanticAI `Agent`.

### Explorer system

Explorers extend `Explorer` ABC (`backend/app/synthesis/explorers/base.py`), implement `system_prompt()` and `user_prompt()`, and self-register via `register_explorer()`. Current explorers: `github`, `claude_code`, `blog`, `hackernews`, `stackoverflow`, `devto`, `website`.

Each explorer's `explore()` method calls `run_agent()` with the DB-backed tool suite from `tools.py`. When a `db_session` and `mini_id` are available (normal pipeline path), findings are written directly to the database. A fallback in-memory path exists for tests.

### Explorer tool suite

`backend/app/synthesis/explorers/tools.py` — `build_explorer_tools()` returns 12 `AgentTool` instances backed by the Evidence DB tables:

| Tool | Purpose |
|---|---|
| `browse_evidence` | Paginate through evidence items for a source |
| `search_evidence` | Keyword search across evidence content |
| `read_item` | Read a full evidence item (content + metadata) |
| `save_finding` | Persist a structured finding (personality, values, skills, etc.) |
| `save_memory` | Save a factual memory entry |
| `save_quote` | Save a behavioral quote with context and significance |
| `save_knowledge_node` | Add a node to the knowledge graph |
| `save_knowledge_edge` | Add an edge between knowledge graph nodes |
| `save_principle` | Add a decision principle (trigger → action → value) |
| `mark_explored` | Mark an evidence item as analyzed |
| `get_progress` | Check exploration progress counters |
| `finish` | Signal exploration complete, set status to "completed" |

### Evidence DB models

`backend/app/models/evidence.py`:

- **`Evidence`**: Raw ingestion data per mini per source (`source_type`, `item_type`, `content`, `explored` flag)
- **`ExplorerFinding`**: Structured findings from explorer agents (`category`, `content`, `confidence`)
- **`ExplorerQuote`**: Behavioral quotes with `context` and `significance`
- **`ExplorerProgress`**: Per-source agent progress tracker (counters for explored items, findings, memories, quotes, nodes; `status`; `summary`)

### Ingestion sources

Implement `IngestionSource` ABC (`backend/app/plugins/base.py`). Registered via plugin registry (`backend/app/plugins/registry.py`). Sources: `github` (default), `claude_code`, `blog`, `stackoverflow`, `devblog`, `hackernews`.

### Database

PostgreSQL via async SQLAlchemy + asyncpg. Neon in production, local PostgreSQL in dev. Migrations managed by Alembic (`backend/alembic/`). Connection config in `backend/app/db.py` — prefers `NEON_DATABASE_URL` over `DATABASE_URL`.

Key models beyond evidence: `Mini`, `User`, `Conversation`, `Message` (chat persistence), `Embedding` (pgvector), `MiniRevision` (pipeline history), `KnowledgeGraph` / `PrinciplesMatrix` (structured outputs).

### Local Dev DB

The codebase is **Postgres-only** — `db.py` uses `asyncpg`, there is no sqlite driver. Migrations and tests against a real DB require Postgres.

For local dev, two supported paths:
1. **Neon dev branch (recommended)** — `neonctl branches create --name dev-<your-feature>` creates a personal branch off main. Set `NEON_DATABASE_URL` to the connection string. This isolates your migration testing without touching prod.
2. **Local Postgres** — install Postgres locally, set `DATABASE_URL=postgresql+asyncpg://localhost:5432/minis`. `NEON_DATABASE_URL` takes priority if both are set.

For unit tests that need DB-shaped objects but no real DB, mock the session (see `tests/test_explorer_tools.py` fixture pattern).

For migrations: never apply to Neon prod directly. Always test against a Neon dev branch first via `NEON_DATABASE_URL=<branch-url> uv run alembic upgrade head`.

The PR preview workflow (`.github/workflows/preview.yml`) creates a `pr-<N>` Neon branch automatically when a PR is labeled `preview`.

### Authentication (Neon Auth + BFF proxy)

1. Frontend uses `@neondatabase/auth` with GitHub OAuth
2. Next.js BFF proxy (`frontend/src/app/api/proxy/[...path]/route.ts`) calls `/api/auth/sync` to upsert user, then issues a service JWT signed with `SERVICE_JWT_SECRET`
3. Backend validates service JWT via `get_current_user` dependency (`backend/app/core/auth.py`)

### LLM integration

All LLM calls go through PydanticAI (`backend/app/core/agent.py`, `backend/app/core/models.py`). Provider selection is driven by `DEFAULT_PROVIDER` env var; model strings use PydanticAI format (`provider:model-name`). `GOOGLE_API_KEY` (or `GEMINI_API_KEY`, which is auto-bridged on startup) is read directly by PydanticAI's Google provider. Langfuse tracing is optional (`LANGFUSE_ENABLED=true`).

### Incremental ingestion

`backend/app/ingestion/` (ALLIE-374 M1) adds three building blocks for delta-fetch:

- **`hashing.py`** — `hash_evidence_content(content, metadata)` produces a deterministic SHA-256 over stripped content + canonically-sorted metadata. Used for mutation detection when re-ingesting the same item.
- **`delta.py`** — `get_latest_external_ids()` and `get_max_last_fetched_at()` query the Evidence table for already-seen items and the most recent fetch timestamp, respectively. The helpers are now wired in `backend/app/synthesis/pipeline.py` during the FETCH stage.
- **Schema additions on `Evidence`** — `external_id` (stable source-side identifier, e.g. commit SHA), `last_fetched_at` (UTC timestamp set on upsert), `content_hash` (SHA-256 from `hashing.py`).

`backend/app/ingestion/github_http.py` (ALLIE-372) consolidates all GitHub REST/GraphQL calls behind a single `gh_request` helper with retry + exponential backoff (handles `429`, rate-limited `403`, transient `5xx`; respects `Retry-After` and `X-RateLimit-Reset` headers; caps sleep at 60 s).

Status:

- **Shipped:** fetch uses `since_external_ids` for unchanged-item skip.
- **Partial / gated:** fetch timestamps support mutation detection and rescan windows, but legacy rows without `external_id` still rely on periodic source-specific backfill for full delta fidelity.

### Per-repo local-clone explorer (primitives)

`backend/app/explorer/` (ALLIE-373 M1) provides the safe primitives for future repo-level analysis:

- **`clone_manager.py`** — Manages persistent, per-mini local clones. Clones are refreshed (`git fetch`) rather than re-cloned across pipeline runs. Paths: `/data/clones/{mini_id}/{slug}` on Fly.io, `~/.minis/clones/…` locally. Trust boundary: no `shell=True`, token injected into URL and never logged, paths derived from trusted inputs (UUID + validated owner/repo strings).
- **`repo_tools.py`** — Read-only filesystem and git tools consumed by LLM agents. Every user-supplied path goes through `_safe_resolve()` which raises `PathTraversalError` if the resolved path escapes the clone root (blocks `../../` traversals and symlink escapes). Binary files are elided rather than sent to the model. No repo code is ever executed.

**RepoAgent fan-out** (`backend/app/synthesis/explorers/repo_agent.py`, ALLIE-388/389) wires these primitives into a per-repository sub-agent that runs unconditionally after the GitHub evidence explorer. For each mini, the top-N repos (default 5, tunable via `REPO_AGENT_MAX`) are cloned locally and explored by an autonomous RepoAgent. Concurrency is controlled by `REPO_AGENT_CONCURRENCY` (default 4) and clone size is capped by `REPO_SIZE_LIMIT_KB` (default 200 MB).

### Evaluation harness

`backend/eval/` (ALLIE-382/385) provides offline fidelity testing:

- **Golden subjects**: `alliecatowo`, `jlongster`, `joshwcomeau` — each defined by a `subjects/<username>.yaml` (display name, why selected, expected voice markers) and `golden_turns/<username>.yaml` (10 source-annotated turns with prompts, reference answers, and rubrics).
- **Runner** (`runner.py`): POSTs each turn to the live `/api/minis/{username}/chat` SSE endpoint and collects the full streamed response.
- **Judge** (`judge.py`): LLM-as-judge scoring — each response is evaluated against the rubric and voice markers; produces per-turn `ScoreCard`s and per-subject `SubjectSummary`.
- **Report** (`report.py`): Writes a Markdown report + machine-readable JSON. Supports `--prior` for regression detection against a previous run.
- **Entrypoint**: `backend/scripts/run_fidelity_eval.py` — run with `uv run python scripts/run_fidelity_eval.py --subjects alliecatowo --base-url http://localhost:8000`.

### Privacy

`source_privacy` column on `Evidence` (ALLIE-367) tags each evidence item as `"public"` or `"private"`. The `claude_code` ingestion source defaults to `"private"` (local machine sessions). The chat system prompt enforces a hard rule: private evidence MAY be paraphrased but MUST NOT be quoted verbatim. The browse/search/read tools surface `source_privacy` in their return payloads so the explorer agents can observe it.

### Rate-limit + admin bypass

- **`gh_request` retry helper** (ALLIE-372): `backend/app/ingestion/github_http.py` — single place to handle GitHub API throttling across all ingestion/explorer code.
- **Normalized admin check** (ALLIE-378): `backend/app/core/auth.py` checks `settings.admin_username_list` (from `ADMIN_USERNAMES` env var, comma-separated, case-insensitive). Null `github_username` is handled explicitly. A successful bypass logs at `INFO` for prod visibility; a failed bypass attempt also logs to avoid silent rate-limit surprises.

## Fidelity Iteration Workflow (added 2026-04-26)

**Validate prompt/synthesis changes in cost-cheap simulation BEFORE writing code.** The pipeline burns Gemini/Anthropic tokens, Fly deploys, and Vercel deploys. Burn one of those budgets per validated change, not per guess.

### The chat-stage validator

`backend/scripts/prompt_diff_test.py` (Anthropic API + Neon read-only):
- Loads a target mini's `system_prompt` + structured fields (voice_profile, principles, etc) from prod Neon
- Applies a programmatic prompt mutation in Python (matching what the code change WOULD do)
- A/B tests original vs mutated prompts against Anthropic on the 7 fidelity-test questions
- Scores responses via `claude-haiku-4-5-20251001` as judge
- Reports side-by-side comparison + delta

Cost: ~$0.50 per run. Time: <2 min. Use BEFORE writing the actual code change.

### Master fix plan

The current sprint plan is mirrored at:
- Repo: `docs/MINIS_FIDELITY_FIX_PLAN.md` (canonical, survives sessions)
- Audits: `/tmp/minis-audit/*.md` (regenerated per session — copy to `docs/audits/` if persisting)
- Tasks: `TASKS.md` at repo root (Linear is full — using markdown for now)

Always cite audit findings by filename when proposing fixes — drift prevention.

## Agent Dispatch Matrix

When dispatching subagents, route by capability:

| Agent class | Best for | Avoid for |
|---|---|---|
| **Claude haiku** | quick exploration, file edits, mechanical synthesis, reading + summarizing | precise code generation in unfamiliar areas |
| **Claude sonnet/opus** | vision interpretation, multi-file refactors, creative judgment, code review with synthesis | trivial tasks (overkill) |
| **Codex** (`Agent` with `subagent_type: codex:codex-rescue`) | precise programming with exact spec, deep debugging, deterministic implementation | open-ended tasks, anything requiring vision-aware interpretation, file writes outside its sandbox |

Codex is a programming beast but its sandbox is read-only filesystem (no writes outside its workspace, often no network). Claude is "cofounder energy" — interprets intent and expands well, but can drift on precision. Distribute load 50/50 to avoid exhausting either quota.

## Anti-Hyperfitting Principle

When extracting personality/voice signal:

- **No `save_*` tool may require knowledge of the mini's specific phrases or behaviors.** Tools must be neutral primitives that any developer mini could use. The signal lives in *narratives* an agent writes (essay-length), not in pre-defined enum values.
- **Voice extraction asks for register patterns**, not literal markers. "Code-switches register by audience formality, leans declarative when frustrated" — yes. "Uses 'fucking' 5x per session" — no, that produces thin mockery and breaks for the next mini.
- **Schema is general across all minis. Content is specific.** A field like `signature_phrases` is wrong because it forces the mini to perform those phrases. A narrative essay describing register dynamics is right because the model can apply the pattern to novel input.

## Narrative-First Principle

The right order is: narrative essays → research → research-backed classifiers / coefficients. Not the other way.

**Why narrative first.** A 1500-word essay describing how a person code-switches register by audience captures more usable signal than `terseness: 0.5` and `humor_type: "deadpan"`. The model can read the essay, find the pattern, mirror it. The cherry-picked coefficient suggests false precision the system doesn't have — what's the difference between `profanity_tolerance: 0.4` and `0.5`? Nothing the corpus can answer.

**Where coefficients are welcome.** Once an aspect has a robust narrative corpus across many minis, we can train classifiers OVER those narratives to extract structured coefficients with calibration data behind them — punctuation distributions, parts-of-speech ratios, hedging rates, etc. That's a research project, downstream of having narratives.

**The discipline this implies.**

- For any new schema field that's a scalar/enum without obvious calibration: replace with `save_narrative(aspect=<name>, narrative=<800-2500 words>)` for now. Coefficients earn their place after research validates them.
- Existing cherry-picked coefficients (`save_voice_profile`'s `profanity_tolerance`, `humor_type`, `terseness`, etc.) are deprecated. Voice signal flows through `save_narrative(aspect="voice_signature")` essays.
- Coefficients we ALREADY have research for (e.g. `confidence: float` from explicit calibration tests, framework `intensity` from agreement-rate measurements) keep their place.

**The pipeline architecture this implies.**

Chief synthesizer is not a "voice-forgery prose writer" that flattens findings into bullet text. It's an orchestrator that fans out 8 aspect-narrative subagents (one per facet of the person), each reading the relevant evidence and writing an essay, then composes the soul document from those essays. Same shape as the audit-conversation pattern that produced this fix plan — agent → essay → chief reads essays → synthesis. We KNOW Sonnet-writes-soul-directly produces high-fidelity output; the pipeline must reach that quality, distributed across fan-out agents so it scales beyond any single agent's context window.

## System Prompt vs Soul Prompt

Two distinct prompts (currently mashed into one `Mini.system_prompt` blob; phase 2 splits them):

- **Universal Mini Prompt** — same for every mini. Lives at `backend/app/synthesis/universal_prompt.py` (post-MINI fix). Contains: identity ("you are a mini"), prediction goal ("predict don't regurgitate"), tool docs, abductive reasoning frameworks, techniques for forecasting human responses to novel stimuli.
- **Soul Prompt** — per-mini, lives at `Mini.soul_prompt` column. Contains: "you are X, you...", structured reasoning model (decision frameworks with ordering + trajectory + revisions), narrative essays per aspect, voice register patterns.

Chat assembly joins them: `UNIVERSAL_PROMPT + soul_prompt + retrieved_narratives + tool_directives`.

## Feature Flags

Source of truth: `backend/app/core/feature_flags.py`

All flags are typed `FeatureFlag` dataclasses registered in `FLAGS`. `is_enabled()` reads the env var at call time — truthy values are `"true"`, `"1"`, `"yes"` (case-insensitive); everything else is falsy.

**Discipline rules**:
- `kind="rollout"` — temporary gate; **must** set `removal_ticket` and `planned_removal` (enforced at import time + tests)
- `kind="kill_switch"` — emergency brake; no removal plan required
- `kind="ops"` — permanent operational toggle; no removal plan required

| Name | Kind | Default | Description |
|---|---|---|---|
| `DEV_AUTH_BYPASS` | ops | `false` | Skip Neon Auth JWT validation and inject a hardcoded dev user. LOCAL + PREVIEW ONLY. |
| `DISABLE_LLM_CALLS` | kill_switch | `false` | Emergency brake: every LLM call returns 503. Use if an API key is compromised. |
| `LANGFUSE_ENABLED` | ops | `false` | Send PydanticAI traces to Langfuse for observability. |

To add a new flag: add a `FeatureFlag` entry to `FLAGS` in `feature_flags.py`. Rollout flags require `owner_ticket`, `removal_ticket`, and `planned_removal` — the module raises `AssertionError` at import if missing.

## Key File Map

| To change... | Modify... |
|---|---|
| Pipeline stages/flow | `backend/app/synthesis/pipeline.py` |
| Soul document prompts | `backend/app/synthesis/chief.py` |
| Memory assembly logic | `backend/app/synthesis/memory_assembler.py` |
| System prompt structure | `backend/app/synthesis/spirit.py` |
| Add/modify an explorer | `backend/app/synthesis/explorers/<source>_explorer.py` |
| Explorer DB tool suite | `backend/app/synthesis/explorers/tools.py` |
| Explorer base class | `backend/app/synthesis/explorers/base.py` |
| Agent loop / PydanticAI wrapper | `backend/app/core/agent.py` |
| Model tier / provider config | `backend/app/core/models.py` |
| Compaction strategy | `backend/app/core/compaction.py` |
| Add an ingestion source | `backend/app/plugins/sources/<source>.py` + register in `registry.py` |
| Chat behavior/tools | `backend/app/routes/chat.py` |
| Mini creation endpoint | `backend/app/routes/minis.py` |
| Admin rate-limit bypass | `backend/app/core/auth.py` (`is_admin_user()`), config via `ADMIN_USERNAMES` |
| Database models | `backend/app/models/` (`mini.py`, `user.py`, `evidence.py`, `conversation.py`, etc.) |
| Database connection | `backend/app/db.py` |
| App config / env vars | `backend/app/core/config.py` |
| Feature flags (add/remove/check) | `backend/app/core/feature_flags.py` |
| Auth flow (backend) | `backend/app/core/auth.py`, `backend/app/routes/auth.py` |
| Auth flow (frontend) | `frontend/src/lib/auth.ts`, `frontend/src/app/api/proxy/[...path]/route.ts` |
| Frontend pages | `frontend/src/app/<route>/page.tsx` |
| API client functions | `frontend/src/lib/api.ts` |
| Local clone management | `backend/app/explorer/clone_manager.py` |
| Repo read tools (agent) | `backend/app/explorer/repo_tools.py` |
| GitHub HTTP + retry helper | `backend/app/ingestion/github_http.py` |
| Evidence content hashing | `backend/app/ingestion/hashing.py` |
| Incremental delta helpers | `backend/app/ingestion/delta.py` |
| Fidelity eval harness | `backend/eval/` (`runner.py`, `judge.py`, `report.py`, `subjects/`, `golden_turns/`) |
| Run fidelity eval | `backend/scripts/run_fidelity_eval.py` |
| Playwright E2E tests | `e2e/specs/` (`smoke.spec.ts`, `create-mini.spec.ts`, `regenerate.spec.ts`) |

## Worktree Setup

This project uses Claude Code worktrees for isolated parallel development. Worktrees are pre-configured:

- **Dependencies are symlinked** (`.venv`, `node_modules`, `.next`) — no reinstall needed
- **Secrets are copied** (`.env`, `.env.local`) — available immediately

To spawn an isolated subagent, use `isolation: "worktree"` in the Agent tool call. The subagent gets its own branch and working directory with everything ready to go.

## Environment Setup

```bash
# 1. Install mise, then install toolchain
curl https://mise.run | sh && mise install

# 2. Backend
cd backend && cp .env.example .env
# Edit .env — set GEMINI_API_KEY (or GOOGLE_API_KEY) and GITHUB_TOKEN at minimum
# Set DATABASE_URL to a PostgreSQL connection string
uv sync

# 3. Run migrations
mise run migrate

# 4. Frontend
cd frontend && pnpm install
# Create .env.local with AUTH_GITHUB_ID, AUTH_GITHUB_SECRET, AUTH_SECRET,
# BACKEND_URL=http://localhost:8000, SERVICE_JWT_SECRET (must match backend)

# 5. Run
mise run dev
```

## Required Environment Variables

**Backend** (`backend/.env`):
- `GEMINI_API_KEY` — Google Gemini API key (auto-bridged to `GOOGLE_API_KEY` for PydanticAI)
- `GITHUB_TOKEN` — GitHub PAT for profile ingestion
- `DATABASE_URL` — PostgreSQL connection (`postgresql+asyncpg://...`)
- `JWT_SECRET`, `SERVICE_JWT_SECRET` — Auth secrets (defaults provided for dev)
- `ENCRYPTION_KEY` — Explicit key material for encrypted user secrets; required outside development
- `LANGFUSE_ENABLED` — Optional: `true` / `false` to enable Langfuse tracing (default `true`)
- `LANGFUSE_PUBLIC_KEY` — Langfuse public API key (required if LANGFUSE_ENABLED=true)
- `LANGFUSE_SECRET_KEY` — Langfuse secret API key (required if LANGFUSE_ENABLED=true)
- `LANGFUSE_HOST` — Langfuse API host (default `https://us.cloud.langfuse.com`)
- `DEFAULT_PROVIDER` — Optional: `gemini` (default), `anthropic`, or `openai`
- `REPO_AGENT_MAX` — Optional: max repos to clone and explore per mini (default `5`)
- `REPO_AGENT_CONCURRENCY` — Optional: max concurrent clone+explore tasks (default `4`)
- `REPO_SIZE_LIMIT_KB` — Optional: skip repos larger than this (default `204800` = 200 MB)
- `ADMIN_USERNAMES` — Optional: comma-separated GitHub usernames granted admin/bypass privileges (default `alliecatowo`)

**Frontend** (`frontend/.env.local`):
- `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET` — GitHub OAuth app credentials
- `AUTH_SECRET` — Neon Auth secret (generate with `npx auth secret`)
- `BACKEND_URL` — Backend URL (`http://localhost:8000` in dev)
- `SERVICE_JWT_SECRET` — Must match backend's value

## Claude Code Commands

- `/mini-review <username>` — Get a code review from a developer mini
- `/mini-chat <username>` — Chat with a developer mini
- `/mini-create <username>` — Create a new mini from a GitHub username
- `/mini-team <action> [usernames...]` — Assemble a team of minis for review/discuss/brainstorm

## API

Backend runs at `http://localhost:8000`. Swagger docs available at `/docs` in development.

- `POST /api/minis` — Create mini `{"username": "torvalds"}`
- `GET /api/minis` — List all minis
- `GET /api/minis/{username}` — Get mini details
- `POST /api/minis/{username}/chat` — Chat with mini (SSE)
- `GET /api/minis/{id}/progress` — Stream pipeline progress (SSE)
- `GET /api/health` — Health check
