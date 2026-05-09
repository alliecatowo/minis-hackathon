# Regen v9 Baseline Stats — 2026-05-09

First-ever measured regen run. v9 = `DEFAULT_PROVIDER=openai` on `gpt-5/o3` stack with $20 credits added mid-flight. **NOT Langfuse-traced** (started before PR #217 langfuse v4 upgrade landed). Use this file as the baseline for future regen comparisons.

## Run metadata
- **PID:** 382640
- **Started:** 2026-05-09 10:53:11 PT (17:53 UTC)
- **Duration in this snapshot:** ~37 min (still running, in EXPLORE → SYNTHESIZE)
- **Mini:** `alliecatowo` (`d2028d10-123b-4c00-ac58-66212d358ce1`)
- **Provider:** OpenAI (gpt-5 STANDARD, gpt-5-mini FAST, o3 THINKING, text-embedding-3-small EMBED)
- **Sources:** github + claude_code

## GitHub API
- **Total REST calls:** 1379 ⚠️ (Wave 4.1 GraphQL co-fetch in PR #220 should cut this 5-10×)
- **GraphQL calls:** 2 (only the existing user-repos query; bundle queries from #220 not yet merged)
- **Reactions endpoint hits:** 500 (Wave 3D shipped + working)
- **Issue-comments hits:** 218 (Wave 3B `fetch_user_issues` working)
- **Rate-limit hits:** 0 (we did NOT hit GitHub limits this run)

## FETCH stats
```
44 repos, 1000 commits, 21 issues, 401 PRs, 0 reviews, 430 issue comments,
17 PR reviews, 40 repo language breakdowns, 150 commit diffs,
0 PR review threads, 116 issue threads, 118 PR commit lists,
31 authored reviews, 0 inline comments, 0 starred repos, 0 watched repos,
0 commit comments, 1531 timeline events, 0 gists, 441 stop reasons
```

**DB delta:** 55 inserted, 5 updated, **4195 skipped (unchanged)** — additive cache working, ~17× write reduction vs cold start.

## OpenAI API
- **Chat completion calls (so far):** 95
- **Status:** 95/95 = 200 OK (after $20 credit top-up; pre-credit hit insufficient_quota on gpt-5)
- **Provider mix:** OpenAI only (Anthropic + Gemini = 0 calls — clean per-provider isolation)

## EXPLORE phase
- **claude_code explorer:** ✅ completed in 6 turns, tokens_in=21473, tokens_out=2504
- **Other explorers:** still in flight

## Langfuse
- **Traces during this run:** 0 (only smoke-test traces from PR #217 setup work)
- **Reason:** v9 started 10:53 PT, PR #217 (langfuse v4 upgrade) opened 11:05 PT. Old v3 `.trace()` API not properly wired, so v9 produces no Langfuse data.
- **Next regen (post #217 merge + redeploy):** WILL trace fully.

## Demo-readiness signal
- Mini status: `processing` (still). Will become `ready` when SYNTHESIZE → SAVE completes.
- Detection: `curl https://minis-api.fly.dev/api/minis/alliecatowo` returns 200 instead of 404 — that's "ready".

## Comparison hooks (future regens)
Use this file as baseline. Future regens after Wave 4.1 GraphQL merge should show:
- GitHub REST calls: 1379 → ~150-300 (5-10× reduction target)
- FETCH duration: 31min → ~5-10min target
- DB writes: similar (additive cache already there)
- LLM cost: similar (synthesis cost not affected by GraphQL change)
- Langfuse traces: 0 → ~150-300 trace count target
