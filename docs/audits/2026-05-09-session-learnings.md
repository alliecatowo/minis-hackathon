# Session Learnings — 2026-05-09

Single-session record from the YC-sprint marathon. Wrote this so the next agent / next session inherits everything we learned today, not just the code we pushed.

## Headline

We unwedged 12 days of accumulated CD failure on a 2-line lint typo, shipped a 4-wave fidelity + ingestion + DX overhaul (Wave 0 → Wave 4) across ~20 PRs, and surfaced a class of "agency-restricting" agent caps that were silently destroying fidelity. Final regen of `alliecatowo` started 10:53 PT and is still in chief synthesis at end of session — first regen with the new ingestion stack (deep fanout, reactions, authored issues, repo-fanout, additive cache).

## Architectural principles that became canon today

### 1. Agency-first agent design
Stored at `~/.claude/projects/.../memory/feedback_agency_first.md`. **No artificial caps** on agent runs (`request_limit`, `max_output_tokens`, `max_turns`, etc). Cap cost via `TokenBudget`; trust the agent. The worst failure mode in agent code is a silent partial-output + wasted-spend caused by an arbitrary mid-run cap. Today's regen v9 cost real $ producing zero `evidence_items` in `repo_agent` because of `request_limit=40`, and dropped a whole `decision_frameworks_in_practice` aspect narrative because `output_tokens_limit=8192` < the model's planned 10526. Both got removed in `fid-fix-rate-leak` PR.

### 2. No-legacy-paths (pre-0.0.1)
Every code change should result in ONE code path. Today's wave 2D deleted ~728 LOC of legacy `write_section` chief synthesis. Today's wave 2C deleted ~275 LOC of `save_voice_profile` cherry-picked coefficients. Same principle applies tomorrow: when a new path lands, delete the old one in the same PR pair.

### 3. Postgres-only test infra (TI.1)
The codebase is postgres-only but several tests use `aiosqlite` mocks that drift from the real schema (today's `register_level` debacle ate hours). Migrate to a Postgres testcontainer per test session. Tracked as TASKS.md TI.1 / GH issue (pending migration to issues).

### 4. Bulk + additive ingestion
`docs/spikes/2026-05-09-bulk-additive-ingestion.md` is canonical. W4.1 GraphQL co-fetch (PR #220) collapses N×REST per PR/issue → 1 GraphQL. W4.2 strict additive cache (PR #215) skips unchanged Evidence rows entirely (~25× write reduction; today's regen showed 4195/4200 skipped). W4.6 profiling hooks (PR #213) instrument every stage so future bottleneck identification is data-driven, not guess-driven.

### 5. PR-driven only — never direct push to main
Even the lint-unblock fix (the most justified "just push it" moment of the day) went through PR #194 → #195 → merged. Discipline preserved review trail + CI gate visibility.

### 6. Worktree isolation for parallel agents
When agents share a working tree, they stomp each other's edits. fid-2e flagged this hazard. Going forward every code-mod agent gets `isolation: "worktree"` (the harness symlinks .venv/.next/node_modules so spinup is fast).

### 7. Rolling-deploy concern (CI.3)
A merge → CD trigger → Fly redeploy mid-pipeline could nuke a running regen's DB writes. Today we deferred merging while regen v9 ran. Long-term fix: separate worker machines OR drain-before-swap deploy strategy. Tracked as CI.3.

## What landed (PRs merged today)

Numbered by PR. ~20 merged, 5 open at end-of-session.

| PR | Subject | Why it matters |
|----|---------|----------------|
| #195 | Lint unblock + 7 backlog commits | Unwedged 12 days of CD outage |
| #196 | Wave 2B reasoning edges | Explorers now emit REJECTS_BECAUSE/PREFERS_OVER edges |
| #197 | Wave 2C deprecate save_voice_profile | -275 LOC; voice routes through narrative essays only |
| #198 | Wave 2A behavioral pre-chief + Wave 2D legacy chief delete | -1500 LOC; behavioral signal feeds chief synthesis |
| #199 | Wave 2E universal/soul prompt split | New `Mini.soul_prompt` column; UNIVERSAL_MINI_PROMPT separated |
| #200 | CD neonctl + 24h stale alarm | Deploy uses neonctl + alarm if no deploy in 24h |
| #201 | Wave 3E evidence envelope backfill | source_uri/evidence_date/raw_context_json across 6 non-GitHub sources |
| #202 | Wave 3D reactions ingestion | PR/issue/comment reactions as evidence with parent linkage |
| #203 | Pipeline chief import hotfix | Removed dead `run_chief_synthesis` import that crashed every regen |
| #204 | Wave 3A local commit-diffs | `git show` fallback before REST for commit patches |
| #205 | Wave 3C repo-fanout wire | `top_repos` populated → RepoAgent fan-out actually fires |
| #206 | Wave 3B authored issues + comments | New `fetch_user_issues()` for non-PR issue corpus |
| #207 | CI workflow_dispatch | Manual CI trigger when synchronize event misfires |
| #212 | CI push trigger for agent branches | CI fires on `codex/**`, `fix/**`, `worktree-agent-**` push |
| #213 | CD pipefail + W4.6 profiling | Migrate fails loud; per-stage timing logged |
| #214 | Langfuse on by default + DB pool 5→20 | Demo polish + perf headroom |
| #216 | Bare-except sweep round 1 (minis.py routes) | 3 silent swallows narrowed + logged |

## Open at end-of-session (waiting on regen completion to merge)

| PR | Subject |
|----|---------|
| #215 | W4.2 strict additive cache |
| #217 | Langfuse v4 + mise auto-env + CLAUDE.md sync |
| #218 | Lefthook pre-push ruff + `mise run sprint-status` |
| #219 | Bare-except sweep round 2 (synthesis + chat + core) |
| #220 | W4.1 GraphQL co-fetch bundles |
| (in flight) | fidelity-rate-leak (remove all agent caps) |
| (in flight) | openai-tier-optimization (cheapest viable mix) |
| (in flight) | tasks-md → GH issues migration |

## Audits written today

- `docs/audits/2026-05-09-codebase-health.md` — 3 critical (silent excepts, langfuse off, no SSR streaming) + 7 high
- `docs/audits/2026-05-09-project-health.md` — vision-parity gap, demo blockers, Linear-cap cleanup
- `docs/audits/2026-05-09-agent-dx-meta.md` — 12 friction points + top 5 ship-this-sprint fixes
- `docs/audits/2026-05-09-regen-v9-baseline.md` — first quantified regen (1379 GH calls, 95 OpenAI calls, 4195 skipped DB writes)
- `docs/spikes/2026-05-09-bulk-additive-ingestion.md` — W4.1-W4.6 implementation roadmap
- `docs/audits/2026-05-09-session-learnings.md` — this file

## Bugs found mid-flight (root-caused, fixed or tracked)

1. **F401 unused imports** in `658e5422d52b_merge_embedding_freshness_heads.py` wedged CI for 12 days → CD never deployed → alliecatowo stuck `processing` since 2026-04-27. Fix: remove imports + retroactive cd.yml hardening.
2. **Sqlite mock schema drift** — `register_level` and 16 other Evidence columns missing → 116 integration tests dead. Fix: extend `tests/fixtures/postgres_mock.py` schema definitions.
3. **pnpm 10 ERR_PNPM_IGNORED_BUILDS** — `onlyBuiltDependencies` declaration in package.json not honored. Fix: pin pnpm to v9 + remove the v10-only `pnpm-workspace.yaml`.
4. **CI synchronize event flaky on agent-pushed branches** — close+reopen + force-push didn't always retrigger. Fix: PR #207 added workflow_dispatch + PR #212 added push trigger for agent branch patterns.
5. **`pipeline.run_chief_synthesis` import after Wave 2D deletion** — 3 regens crashed before chief could fire. Fix: PR #203 removed the dead import + the legacy `else` branch.
6. **`request_limit=40` killing repo_agent** — 233s of OpenAI spend, 0 evidence_items returned. In-flight fix: full agency-restoration sweep.
7. **`output_tokens_limit=8192` dropping `decision_frameworks_in_practice` aspect** — silent narrative loss. Same fix.
8. **gpt-5 `insufficient_quota` until $20 credits added** — burnt 2 regens before user topped up.
9. **CD migrate step misconfigured** — pointed at 127.0.0.1 because `NEON_DATABASE_URL` secret missing. Fix: PR #200 added neonctl path + secret set as fallback.
10. **Langfuse `.trace()` v3 API in pipeline didn't actually report** — v9 regen produced 0 traces despite credentials being set. Fix: PR #217 upgrades to v4 `start_observation()`.

## What still hurts (next session)

1. **Per-regen cost is high** — 95 OpenAI calls + 11 chief aspect agents × 10k+ output tokens each. Pricing-audit agent in flight to recommend cheaper tier mix.
2. **Pipeline takes ~45+ min for FETCH alone post-Wave-3** — the new endpoints (reactions, authored issues, fetch_user_issues, repo agent fan-out) added massive REST volume. W4.1 GraphQL bundles (PR #220) should slash 5-10×.
3. **Mini fidelity not yet evaluated post-Wave-2** — chief now has 11 aspect narratives + behavioral_context grounding + reasoning edges, but we haven't run fidelity_eval against alliecatowo since regen completes.
4. **No mini-revision diff tool** (TI.4) — can't compare two regens of the same mini to see what changed soul-doc-wise.
5. **No live regen TUI** (TI.6) — current visibility is `tail -f log` + log-grep. `mise run regen-watch` would massively improve dev experience.
6. **Rolling-deploy concern** (CI.3) — still unfixed. Must hold merges during regens until separate worker machines or drain-before-swap exists.
7. **Frontend SSR streaming unused** (codebase audit #3) — profile page is fully client-rendered; React 19 SSR-stream would massively improve TTFB for demo polish.
8. **GitHub App not installed on any public repo** (project audit demo blocker #4) — YC step 7 CTA needs proof-of-concept install.
9. **Linear at cap, TASKS.md → GH issues migration in flight** — once that lands, we have an infinite, queryable backlog labeled by group (fidelity / ingestion / dx / ci-cd / infra).

## Final session deltas

- LOC delta: roughly **net negative** thanks to Wave 2C (-275) + Wave 2D (-1500) — we deleted more code than we added even with all the new ingestion features.
- Test count: ~2050 passing (up from initial 805+ baseline; today's drift fixed +200 tests).
- Branches in repo: down from ~196 to manageable count after w3-merger + branch-janitor sweeps (some worktree-agent-* still locked but inert).
- GH issues created today (audit-driven + demo-blocker): 12+ (188-211 range).
- New Linear tickets: 0 (cap), all migrated to TASKS.md → GH issues.
- Memory entries added: `feedback_agency_first.md`, `feedback_dispatch_protocol.md`.

## Recommended path for next session

1. Wait for v9 regen to complete + chat smoke-test alliecatowo on prod.
2. Merge backlog of 5-7 open PRs in dependency order.
3. Trigger ONE clean post-everything regen as the canonical baseline.
4. Run fidelity_eval against the new alliecatowo + jlongster + joshwcomeau.
5. Compare to baseline numbers in `2026-05-09-regen-v9-baseline.md`.
6. Tackle next session's top items in priority order: rolling-deploy fix, GitHub App install, frontend SSR streaming, mini-revision-diff tool, regen-watch TUI.
