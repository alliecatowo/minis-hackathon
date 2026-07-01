# TASKS.md → GH Issues Migration Progress

**Status:** Rate-limited at label creation step. Core quota resets at 2026-05-09 11:48 UTC.

## Labels to Create
- `fidelity` — Voice/fidelity pipeline improvements — color: #0075ca
- `ingestion` — Data ingestion and GitHub API work — color: #e4e669
- `dx` — Developer experience and tooling — color: #7057ff
- `ci-cd` — CI/CD pipeline and deployment — color: #d73a4a
- `infra` — Infrastructure and database — color: #008672

## Existing Issues (do not duplicate)
- 208: CRITICAL: silent exception swallowing in minis.py + ~40 sites
- 209: DEMO: flip LANGFUSE_ENABLED=true for prod traces
- 210: perf: bump DB pool to 20-30 conns for parallel synthesis
- 211: perf: SSR-stream profile page (React 19 + Next 16)

## Issues to Create (all non-completed tasks)

### Label: ingestion
- [Q1.1] Add missing discussion primitives in bulk (status: in-progress)
- [Q1.2] Replace per-commit API fanout with local git mining (status: in-progress)
- [Q2.1] Synthesis guardrails so new evidence is not choked out
- [Q2.2] Fidelity validation loop on refreshed corpus
- [Q3.2] Reingest alliecatowo after Q1/Q2/Q3 land, then evaluate
- [W4.1] GraphQL co-fetch (kill REST fanout)
- [W4.2] Strict additive cache
- [W4.3] github_archive auto-wire
- [W4.4] OpenAI Batch API for explorers + aspect agents
- [W4.5] Multi-task per LLM call
- [W4.6] Profile bottlenecks (per-stage timing + token-count log)

### Label: fidelity
- [P1.1] Delete chat.py:1019-1029 voice suppression
- [P1.2] chat.py:1001-1019 conditional tool use + register-match rule
- [P1.3] agent.py:306,478 max_tokens 16384 → env-driven default 1500
- [P1.4] spirit.py:197 add voice_profile parameter, inject register-pattern block
- [P1.5] pipeline.py:1440 load latest voice_profile finding, pass to build_system_prompt
- [P1.6] Lint sweep (1 known F401 in tests/test_mini_258_rate_limit_fixes.py)
- [P1.V] Run prompt_diff_test.py against alliecatowo, verify mutated > original by ≥1.0pt
- [P2.1] New save_narrative tool + explorer_narratives table
- [P2.2] Reasoning RelationType enum additions
- [P2.3] save_finding evidence grounding
- [P2.4] Register-tagged quotes: ExplorerQuote.register_level enum
- [P2.5] Split Mini.system_prompt → universal_prompt + Mini.soul_prompt
- [P2.V] Pipeline-stage test infrastructure (cassette/replay LLM calls)
- [P3.1] New backend/app/synthesis/universal_prompt.py
- [P3.2] Soul prompt rewrite (spirit.py)
- [P3.3] Chief synthesizer rewrite (chief.py)
- [P3.4] 8 aspect agents (aspect_agents.py)
- [P3.5] Per-repo essay agent
- [P3.6] claude_code_explorer.py:42 add explicit signal_mode guidance
- [P3.7] Verify behavioral_context.py fix on fresh pipeline run
- [P4.1] GitHub ingestion depth (250 → 5,000+ items)
- [P4.2] Abductive feedback loop in pipeline.py
- [P4.3] Promote personality/behavioral/motivations into orchestration loop
- [P4.4] Eval gate in CI
- [P5.1] Audit all save_* tools
- [P5.2] Deprecate or rename signature_phrases
- [P5.3] Personality typology gated as optional enrichment

### Label: dx
- [TI.4] Mini revision diff / version compare
- [TI.5] Full observability quantification
- [TI.6] Live regen TUI / observability CLI

### Label: ci-cd
- [CI.3] Rolling deploy that doesn't kill long processes

## Next Steps After Rate Limit Resets
1. Create labels
2. Create issues in batches with 1s sleep between calls
3. Rewrite TASKS.md as pointer file
4. Commit + push + open PR
