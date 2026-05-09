# Minis Fidelity Sprint — Active Tasks

> Linear is at capacity; we track active work here until it clears. After clear, port to MINI-260+ tickets. Master plan: [`docs/MINIS_FIDELITY_FIX_PLAN.md`](docs/MINIS_FIDELITY_FIX_PLAN.md).

## How to use this file

- Pick a `[ ]` task that has all dependencies (tasks above marked `[x]`)
- Update status as you go: `[ ]` → `[~]` (in progress) → `[x]` (done)
- Add `(owner: name)` if claimed
- Add `(blocked: reason)` if blocked
- New tasks go in the appropriate phase section
- When Linear is back, port active rows to tickets and replace this file with a pointer

## Status legend
- `[ ]` open / available
- `[~]` in progress
- `[x]` done
- `[!]` blocked

---

## Execution Queue — Bulk Ingest Reset (2026-04-26)
Goal: make GitHub ingestion bulk-first + discussion-complete, then preserve new signal through synthesis and improve dev DX for repeatable long runs.

- [x] **Q0.1** Primitive matrix audit (GitHub: ingested vs missing vs bulk endpoint vs local-clone substitute)
- [x] **Q0.2** Org data scope control flag (default OFF): explicit opt-in for org/team data ingestion
- [~] **Q1.1** Add missing discussion primitives in bulk: issue/pr timeline events, reactions, commit comments, gist comments, watched/subscriptions
- [~] **Q1.2** Replace per-commit API fanout default with local git mining for commit/diff evidence (API detail as fallback only) — see `docs/audits/2026-04-26-github-ingestion-call-graph-and-rate-cost.md`
- [x] **Q1.3** Ingestion run telemetry: stop reasons + budget exhaustion visibility + source-level counters
- [ ] **Q2.1** Synthesis guardrails so new evidence is not choked out (relevance weighting, narrative coverage checks)
- [ ] **Q2.2** Fidelity validation loop on refreshed corpus (focused allie eval turns + regression checks)
- [x] **Q3.1** Dev DX: one-command forced full reingest path + resumable long-run workflow
  - Notes (2026-04-26 spike):
  - Add minimal operator surface: `ingest-full`, `ingest-resume`, `ingest-status`, `ingest-quick-check`.
  - Land script/API primitives first (`regen_mini.py --force-github-reingest --resume` + `scripts/ingest_status.py`), then add `mise` wrappers.
  - Current `--force-github-refresh` only clears `IngestionData` cache; it does not guarantee full `Evidence` reingest.
  - Landed: `--force-github-reingest` now bypasses incremental `since_external_ids` for GitHub + clears cache; `--resume` implemented; `ingest-resume` task added.
- [ ] **Q3.2** Reingest alliecatowo after Q1/Q2/Q3 land, then evaluate

---

## Phase 1 — Surgical fixes (TODAY)
Goal: lift fidelity 4.9 → ~6/10 by removing chat-time suppressors. No pipeline re-run needed.

- [ ] **P1.1** Delete chat.py:1019-1029 voice suppression (`framework application, not persona voice`)
- [ ] **P1.2** chat.py:1001-1019 conditional tool use + register-match rule
- [ ] **P1.3** agent.py:306,478 max_tokens 16384 → env-driven default 1500
- [ ] **P1.4** spirit.py:197 add `voice_profile` parameter, inject register-pattern block
- [ ] **P1.5** pipeline.py:1440 load latest voice_profile finding, pass to build_system_prompt
- [ ] **P1.6** Lint sweep (1 known F401 in tests/test_mini_258_rate_limit_fixes.py)
- [ ] **P1.V** Run prompt_diff_test.py against alliecatowo, verify mutated > original by ≥1.0pt

PR target: `fix/voice-rendering-surgery`

---

## Phase 2 — Schemas (THIS WEEK)
Goal: support per-aspect narratives, reasoning edges, register-tagged quotes, soul/system split.

- [ ] **P2.1** New `save_narrative(aspect, narrative, confidence)` tool + `explorer_narratives` table
  - 8 aspects: voice_signature, decision_frameworks_in_practice, values_trajectory_over_time, audience_modulation, conflict_and_repair_patterns, technical_aesthetic, philosophical_priors, architecture_worldview
  - Alembic migration
- [ ] **P2.2** Reasoning RelationType enum: add `rejects_because`, `prefers_over`, `trades_off`, `decides_based_on`, `escalates_when`, `ignores_when`. Update save_knowledge_edge to require evidence_ids + reasoning_text
- [ ] **P2.3** save_finding evidence grounding: add `evidence_ids: list[str]`, `support_count: int`, `contradictions: list[str]`, `counterevidence_ids: list[str]`. Move temporal_signal out of string-prefix into JSON key
- [ ] **P2.4** Register-tagged quotes: ExplorerQuote.register_level enum (`casual_unfiltered | casual_filtered | technical_precise | formal_written`)
- [ ] **P2.5** Split Mini.system_prompt → universal_prompt (constant) + Mini.soul_prompt (per-mini)
- [ ] **P2.V** Pipeline-stage test infrastructure (cassette/replay LLM calls) — see `[Future]` in master plan

---

## Phase 3 — Prompt rewrites (THIS WEEK / NEXT)
Goal: implement the 8-aspect narrative architecture; chief becomes synthesizer of essays not concatenator of bullets.

- [ ] **P3.1** New `backend/app/synthesis/universal_prompt.py` — universal mini prompt template (identity, prediction goal, tool docs, abductive frameworks)
- [ ] **P3.2** Soul prompt rewrite (spirit.py): reorder frameworks-first; render `decision_order` as ordered checklist (stop collapsing to single token at line 79); inject 2-4 most-relevant aspect narratives via 3-tier sideloading
- [ ] **P3.3** Chief synthesizer rewrite (chief.py): replace 8-section prose contract with reasoning-model write path; add `get_narratives(aspect?)` tool; add 80% senior-engineer rubric ("would this sentence be true of any senior? if yes, discard"); allow `invoke_specialist_explorer` mid-synthesis
- [ ] **P3.4** 8 aspect agents (`backend/app/synthesis/aspect_agents.py`) — each writes 800-2500 word narrative via save_narrative; run after per-source explorers; read access to all findings/quotes/principles
- [ ] **P3.5** Per-repo essay agent — extend repo_agent.py to write 1500-word "voice in this repo" + "decision frameworks visible in this repo" essays via save_narrative
- [ ] **P3.6** claude_code_explorer.py:42 add explicit signal_mode guidance (conflicts_first, reversals_first, frustrations_first)
- [ ] **P3.7** Verify behavioral_context.py fix (commit 8ccc87e) on fresh pipeline run; move contradictions out of summary string into typed `contradictions[]` field

---

## Phase 4 — Architecture (NEXT SPRINT)
Goal: 20-28x evidence depth, abductive feedback loop, eval gating in CI.

- [ ] **P4.1** GitHub ingestion depth (250 → 5,000+ items)
  - Remove `[:5]` slice on reviewed PRs (github.py:562)
  - Paginate all search calls via `gh_request` retry helper (currently bypassed)
  - Raise/remove hard caps (commit_diff 20, pr_discussion 15, pr_review 15)
  - Add `fetch_user_issues()` for non-PR issues
  - Add `pr_hunk` evidence type with `parent_external_id` linkage
  - Add `parent_external_id` field to EvidenceItem
  - Add reactions, discussions, releases ingestion (P1, P2 in audit)
  - Local clone fallback for truncated diffs
- [ ] **P4.2** Abductive feedback loop in pipeline.py:1036 — after explorers finish, detect contradictions, dispatch second-round agents to resolve
- [ ] **P4.3** Promote personality/behavioral/motivations into orchestration loop (BEFORE chief, not after)
- [ ] **P4.4** Eval gate in CI — fidelity_test gates merges below threshold (start 6/10, raise as we improve)

---

## Phase 5 — Anti-hyperfitting hardening (CONTINUOUS)
Cross-cutting discipline applied to every PR in 1-4.

- [ ] **P5.1** Audit all save_* tools — none may require knowledge of mini's specific phrases
- [ ] **P5.2** Deprecate or rename signature_phrases (currently in voice_profile schema) — repurpose as register-example samples, not seed phrases
- [ ] **P5.3** Personality typology (MBTI/Big Five) gated as optional enrichment, not core synthesis budget

---

## Audit reference

Latest fidelity audits live at `/tmp/minis-audit/*.md` during a session:
- `01-synthesis-drift.md` — chief.py is voice-forgery, not reasoning model
- `02-extraction-drift.md` — no reasoning edges, save_voice_profile not register-scoped
- `03-data-forensics-LIVE.md` — REAL Neon: gold IS captured, lost in synthesis
- `06-chat-voice-drift.md` — chat.py:1021 explicit voice suppression
- `09-voice-profile-lifecycle.md` — voice_profile is write-only (chain unplugged)
- `10-longform-prose-gap.md` — no save_narrative tool; 8 aspects need essays
- `07/08-pipeline-arch / voice-extraction-haiku.md` — single-pass, no abductive loop
- `github-depth-audit` (codex agent afa2392e, 2026-04-26) — 250-item ceiling root-caused

If these are missing locally (new session), regenerate via codex/claude agent dispatch — see master plan.

---

_Last updated: 2026-04-26 by Claude session synthesis after 6 parallel audits._

---

## 2026-05-09 New tasks (user directives, end of session)

### TI.4 — Mini revision diff / version compare
The `MiniRevision` table tracks pipeline run history. We need a way to DIFF two revisions of the same mini side-by-side: soul prompt diff, principle additions/removals, narrative deltas, evidence count change, decision-framework changes. Could be a CLI (`mise run mini-diff alliecatowo --rev1 N --rev2 M`) and/or a frontend `/m/{user}/history` page. Also surface the Langfuse trace URL per revision so we can visually diff the LLM call timeline.

### TI.5 — Full observability quantification
Now that Langfuse is wired (post #217 merge), every regen should produce a structured "regen report" at end:
- GitHub API: # requests, # rate-limit hits, # bytes downloaded, per-endpoint counts
- LLM API: # calls per provider, total tokens in/out, $ cost estimate, longest span
- DB: # inserts, # superseded (additive cache), # skipped-unchanged
- Time per stage (already ~landing in #213 W4.6 profiling)
- Surface all in Langfuse dashboard via `start_observation` metadata + a single SUMMARY trace per run.

### CI.3 — Rolling deploy that doesn't kill long processes
Current Fly deploy strategy likely terminates running pipeline processes when machines roll. Need either:
- (a) Run regens on dedicated worker machines (not on the API machine), OR
- (b) Mark pipeline runs as "in flight" in DB and have deploy script pause + drain before swap, OR
- (c) Move regen execution off Fly entirely (a worker queue / separate service).
Until fixed: HOLD all merges + deploys when a regen is mid-flight. (This is why I'm sitting on PRs 213-220 right now.)


### TI.6 — Live regen TUI / observability CLI
`mise run regen-watch alliecatowo` — interactive terminal UI that connects to a running regen and shows:
- Current stage (FETCH | EXPLORE | SYNTHESIZE | SAVE) + per-explorer progress bars
- Live token spend (totals + per-stage)
- Live API request counts (GitHub + each LLM provider) with rate-limit gauges
- Mini revision number being created
- Estimated time remaining + ETA
- "Cancel" hotkey that gracefully aborts (no half-saved state)
- Tail of Langfuse trace URL so you can click through

Foundation: pipeline.py already streams `PipelineEvent` SSE events. Build a textual/rich TUI consuming the events. Bonus: add `mise run regen-stats LATEST` for a post-mortem summary table.

