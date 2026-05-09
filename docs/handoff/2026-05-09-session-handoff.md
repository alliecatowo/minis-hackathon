# Minis YC-Sprint Session Handoff — 2026-05-09 (~12:00 PT)

> Paste this whole doc into your next session. Cheaper model is fine — most remaining work is mechanical merging + verification + 1-2 small fixes.

## TL;DR (read this first)

Allie burned ~10 hours on YC-readiness. Unwedged 12 days of broken CD. Shipped 17 PRs across 4 waves (fidelity + ingestion + observability + DX). Surfaced and partially fixed a "agent agency" anti-pattern — `request_limit=40` and `output_tokens_limit=8192` were silently dropping fidelity for $$$ spend. Final regen of `alliecatowo` is mid-flight as I write this; **multiple chief aspect narratives degraded due to the output_tokens cap**, so this regen's soul doc will be partial. The fix is in flight (PR #221 from `w4-fidelity-rate-leak`). Next session priority: land the fix, do ONE clean regen, smoke-test fidelity, demo.

## Current state of the world

### Prod
- **https://my-mini.me** → frontend up, Vercel deploys working
- **https://minis-api.fly.dev/api/health** → 200 ✓
- **https://minis-api.fly.dev/api/minis/alliecatowo** → still 404 (mini stuck `processing` since 2026-04-27, regen in flight)
- **Other minis** (joshwcomeau, jlongster) → ready ✓
- **CD pipeline** → unwedged, deploys fire on every main push (12-day outage resolved)
- **Langfuse** → `LANGFUSE_ENABLED=true`, secrets in GH + Fly, prod traces will flow on next deploy

### Regen v9 (in-flight at handoff)
- PID 382640, started 10:53 PT, ~50 min in
- Provider: OpenAI gpt-5/o3 stack (after $20 credit top-up, no more `insufficient_quota` errors)
- FETCH complete: 1379 GitHub REST calls, 4195/4197 Evidence rows skipped (additive cache works)
- EXPLORE complete (claude_code 6 turns, github explorer ran)
- SYNTHESIZE in-flight: **5+ aspects degraded** because `output_tokens_limit=8192` is too low for narrative essays. Resulting soul doc will be missing those aspect narratives.
- Will eventually land as `status=ready` but with partial fidelity. **Don't trust this regen for fidelity eval — it's the baseline-of-broken-output.**
- Process needs to finish to free resources before next regen.

### Branches
- `main` is the canonical truth — 17+ PRs merged today
- 5 open PRs (215, 217, 218, 219, 220) ready or near-ready, holding for merge
- 3 agents in flight pushing more PRs (rate-leak, pricing-audit, tasks-to-issues)
- ~80 stale `worktree-agent-*` branches in `~/.claude/worktrees/` from prior sessions — could prune for cleanup

## What's open right now

### Open PRs (verify CI green, then merge in this order)

| # | Branch | What | Notes |
|---|--------|------|-------|
| 215 | fix/w4-2-strict-additive-cache | W4.2 strict additive cache | One backend test had failed earlier — may need test fixes after rebase |
| 217 | fix/langfuse-sync | Langfuse v4 + mise auto-env + CLAUDE.md sync | Backend test failed earlier — likely pyproject.toml needs `langfuse>=3.0.0` to install in CI |
| 218 | feat/dx-lefthook-sprint-status-v2 | lefthook pre-push ruff + sprint-status mise task | setup-db job had failed earlier — investigate |
| 219 | fix/bare-except-sweep-round-2 | 9 sites narrowed across synth/chat/core | Should be clean |
| 220 | feat/w4-1-graphql-cofetch | GraphQL co-fetch for PR + issue bundles | Should be clean; risk: GraphQL field names not verified live |
| (incoming) | fix/agent-request-limit-hemorrhage | **CRITICAL** — Remove all artificial agent caps per agency-first principle | Probably also fixes output_tokens_limit=8192 |
| (incoming) | fix/openai-tier-optimization | Cheaper OpenAI model mix per pricing audit | Worth merging before re-regen |
| (incoming) | chore/migrate-tasks-to-gh-issues | TASKS.md → GH Issues (Linear capped) | Cleanup only |

### Merge order rationale
Most PRs are independent. The CRITICAL ones are the rate-leak fix (must land before next regen so we don't lose another aspect-narrative to capping) and the GraphQL co-fetch (massive FETCH speedup for next regen). Others are demo polish + observability.

### In-flight agents at handoff
- `w4-fidelity-rate-leak` — fixing request_limit=40 + output_tokens_limit=8192 + sweep all artificial caps
- `w4-pricing-audit` — recommending cheapest viable OpenAI model mix (gpt-5/o3 is expensive)
- `w4-tasks-to-issues` — porting TASKS.md to GitHub Issues (Linear at cap)

Their team is `minis-yc-sprint`. Check `~/.claude/teams/minis-yc-sprint/config.json` if you need to message them.

## What to do first in next session

1. **Wait for v9 regen to actually finish.** Check `tail -f /tmp/regen-alliecatowo-v9-gpt5-credits-2026-05-09.log`. Look for `Pipeline terminal status=...` line. Then:
   - If `status=ready` → mini will be queryable on prod (can curl), but its soul doc has degraded aspects per the output_tokens_limit bug. Do NOT use this regen as the demo baseline.
   - If `status=failed` → just kill and move on.
   - Mini detail endpoint will return 200 once regen completes regardless of partial-narrative degradation.

2. **Merge the in-flight rate-leak PR** (highest priority). It removes artificial agent caps. Verify it has the `output_tokens_limit` removal too (I told the agent twice). Without this PR, the next regen will produce another partial-narrative soul doc.

3. **Merge the rest of the open PRs** in dependency order (215 → 217 → 218 → 219 → 220). Each may have CI to fix. Some won't trigger CI on synchronize event (today's repeated bug); use `gh workflow run ci.yml --ref <branch>` (workflow_dispatch was added in PR #207) to force fire.

4. **Sync main locally** + verify backend imports + run `cd backend && uv run pytest -q --ignore=tests/integration` for green local run.

5. **Restart regen v10** as the "everything-merged baseline":
   ```bash
   cd backend && set -a && source .env && set +a && \
   nohup env DEFAULT_PROVIDER=openai PYTHONPATH=. \
     uv run python scripts/regen_mini.py alliecatowo \
     > /tmp/regen-alliecatowo-v10-final-2026-05-XX.log 2>&1 &
   disown
   ```

6. **Smoke-test fidelity** when v10 completes:
   ```bash
   cd backend && uv run python scripts/run_fidelity_eval.py \
     --subjects alliecatowo,jlongster,joshwcomeau \
     --base-url https://minis-api.fly.dev \
     --out /tmp/eval-2026-05-XX.md
   ```
   Then compare against `docs/audits/2026-05-09-regen-v9-baseline.md` numbers (expect: GH calls 1379 → ~150-300 with GraphQL, all aspect narratives present, ~70% cost reduction with optimized model mix).

7. **Deploy fly + verify chat on prod**:
   ```bash
   curl https://minis-api.fly.dev/api/minis/alliecatowo  # 200 = ready
   curl -X POST https://minis-api.fly.dev/api/minis/alliecatowo/chat \
     -H "Content-Type: application/json" -d '{"message":"what do you think about microservices?"}'
   ```
   Read the response. Does it sound like Allie? If generic/Wikipedia → fidelity work continues.

## What we learned today (don't repeat these mistakes)

### Anti-patterns
1. **Artificial agent caps** (`request_limit=40`, `max_output_tokens=8192`, `max_turns=N`) — silent fidelity drops + wasted spend. Cap cost only. See `~/.claude/projects/.../memory/feedback_agency_first.md`.
2. **`try/except ImportError` fallbacks that hide real bugs** — `from chief import run_chief_synthesis` was deleted by Wave 2D, but the try-except in pipeline.py raised `NotImplementedError` instead of crashing loud. Lost 3 regens to this. Pattern: never except-raise-different to hide a missing import; let it crash.
3. **`pull_request.synchronize` event is flaky on agent-pushed branches** — workflow_dispatch + push trigger backups (PR #207, #212) are essential.
4. **CI/CD silently swallowing migrate failures** — fixed in PR #213 with `set -euo pipefail` + alembic-current assertion.
5. **Sqlite mocks in a postgres-only codebase** — schema drift = hours of phantom test failures. Replace with testcontainers Postgres (TI.1).
6. **Multiple agents stomping on the same working tree** — always use `isolation: "worktree"` for code-mod agents.
7. **Direct push to main even for "tiny" fixes** — discipline the PR workflow even at 1-line scope. Today's lint fix went through PR #194/#195 to preserve the trail.

### Patterns that worked
1. **Wave-tiered parallel agent dispatch** — spawn 5-7 sonnet agents in worktrees on independent slices of work, let them PR back, merge greens. Did 3 waves successfully today.
2. **Append to TASKS.md when Linear is capped** — `TASKS.md` is the canonical sprint board until migration to GH Issues completes (in flight).
3. **`gh issue create` for audit findings** — opens labeled issues for every CRITICAL / HIGH from each audit, gives instant Linear-replacement workflow.
4. **`mise run sprint-status`** (PR #218) — when AFK, this 1-pager shows everything in one screen. Use it.
5. **PR-driven agent workflow with strict refs** — every PR body says `Refs MINI-111` (umbrella ticket) so the trail is consistent.
6. **Background `nohup` regen + `disown`** — survives shell exits and lets you tail the log from any session.

### Repo gotchas
- The repo dir is `minis-hackathon` but canonical remote is `alliecatowo/minis-ai`. Never push to `alliecatowo/minis-hackathon` (legacy).
- `gh` rate limit is 5000/hr — heartbeat polling can blow it. Use ScheduleWakeup + sparse cron for AFK observability.
- Neon free tier has a branch quota (~25 active). Today's session deleted 5+ stale branches to free room. Keep `mise run neon-gc` on the wishlist.
- Regen runs LOCALLY (not on Fly). Killing Fly machines = no impact on a running regen. But CD-redeploy mid-regen = could nuke the API if a synthesis-write coincides with machine-roll. Hold merges during regens.
- Worktree shared `.env` causes provider surprises. Copy or override per-agent.

## Files to read first

Required reading for any next-session agent:
- `docs/VISION.md` — north star (decision-framework cloning, 5-tier value ladder)
- `CLAUDE.md` — repo guide (recently updated with Observability section, mise auto-env, Langfuse refs)
- `TASKS.md` — current sprint board (until migrated to GH issues)
- `docs/MINIS_FIDELITY_FIX_PLAN.md` — Phase 1-5 fidelity master plan
- `docs/spikes/2026-05-09-bulk-additive-ingestion.md` — Wave 4 bulk + cache architecture
- `docs/audits/2026-05-09-session-learnings.md` — comprehensive session record (this companion)
- `docs/audits/2026-05-09-regen-v9-baseline.md` — first measured regen for future comparison
- `docs/audits/2026-05-09-codebase-health.md` — 3 critical + 7 high codebase items
- `docs/audits/2026-05-09-project-health.md` — vision parity + demo blockers
- `docs/audits/2026-05-09-agent-dx-meta.md` — 12 friction points + top 5 fixes
- `~/.claude/projects/-home-Allie-develop-minis-hackathon/memory/MEMORY.md` + linked feedback files

## Stack snapshot

- Backend: FastAPI + SQLAlchemy + asyncpg (Postgres only) + PydanticAI + pgvector. Python 3.13. uv.
- Frontend: Next.js 16 + React 19 + Tailwind v4 + shadcn/ui + pnpm 9 (pinned).
- Infra: Fly.io (backend), Vercel (frontend), Neon (Postgres), Langfuse (LLM tracing), GH Actions (CI/CD).
- Tooling: mise (auto-loads `backend/.env` after PR #217), lefthook (pre-push ruff after PR #218).
- LLM provider stack (current defaults): OpenAI gpt-5 STANDARD / gpt-5-mini FAST / o3 THINKING / text-embedding-3-small EMBED. **Pricing-audit agent is recommending cheaper alternatives — check the audit doc when it lands.**

## Demo-day Top 5

1. **Fidelity must hit ≥7/10 on the eval** — Wave 2 + 3 + the rate-leak fix should get us there. Need fresh regen + eval to confirm.
2. **Frontend mini profile page must render the post-Wave-2 soul prompt + 11 narratives correctly** — codebase audit critical #3 flagged this; not yet verified post-merge.
3. **Scorecard UI must align with the post-Wave-2 schema** — project audit demo blocker #2.
4. **Install GitHub App on at least one public repo for live PR demo** — project audit demo blocker #4. Or document CLI fallback path explicitly.
5. **PredictionFeedbackMemory outcome loop must close end-to-end** — project audit demo blocker #5.

## Final notes

- Allie's tone: hates Wikipedia-flat synthesis output. Wants distinctive voice + framework cloning. Anti-hyperfitting principle is sacred — never extract literal phrases, always extract patterns.
- Linear at cap; TASKS.md migration to GH issues in flight. Once landed, use `gh issue list --label fidelity --state open` etc. as the primary backlog query.
- $20 OpenAI credits added today; before that we hit `insufficient_quota` on gpt-5. Pricing-audit agent will help us avoid burning through it.
- v9 regen produced 50+ minutes of $$$ spend with degraded chief output. The rate-leak PR is the critical-path unblock for the demo.

Good luck, future-me. The plumbing is mostly fixed. Now we polish for YC.
