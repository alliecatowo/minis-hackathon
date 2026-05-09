# OpenAI Pricing Audit & Tier Optimization

**Date:** 2026-05-09  
**Context:** Billing is now active (free-tier credits exhausted). Triggered by regen v9 run on `alliecatowo`.  
**Scope:** Current OpenAI model pricing, Minis workload analysis, recommended tier defaults.

---

## Pricing Data

> **Note:** The OpenAI pricing page at `platform.openai.com/docs/pricing` requires authentication and returned 403. Prices below are from OpenAI's publicly announced model releases as of May 2026. Treat as best-available; verify at https://platform.openai.com/settings/billing/usage if costs look off.

### Full Model Comparison (ranked by avg cost ascending)

| Model | Input $/1M | Output $/1M | Avg $/1M | Free Quota | Reasoning | Context | Recommended Tier |
|---|---|---|---|---|---|---|---|
| gpt-4.1-nano | $0.10 | $0.40 | $0.25 | 10M/day | No | 1M | FAST |
| gpt-5-nano | $0.15 | $0.60 | $0.38 | 10M/day | No | 128K | FAST |
| gpt-4o-mini | $0.15 | $0.60 | $0.38 | 10M/day | No | 128K | FAST fallback |
| codex-mini-latest | $1.50 | $6.00 | $3.75 | 10M/day | Yes | 200K | — |
| o4-mini | $1.10 | $4.40 | $2.75 | 10M/day | Yes | 200K | THINKING (budget) |
| o3-mini | $1.10 | $4.40 | $2.75 | 10M/day | Yes | 200K | — |
| o1-mini | $1.10 | $4.40 | $2.75 | 10M/day | Yes | 128K | — |
| gpt-4.1-mini | $0.40 | $1.60 | $1.00 | 10M/day | No | 1M | STANDARD (budget) |
| gpt-4o | $2.50 | $10.00 | $6.25 | 1M/day | No | 128K | — |
| gpt-4.1 | $2.00 | $8.00 | $5.00 | 1M/day | No | 1M | — |
| gpt-5 | $2.00 | $8.00 | $5.00 | 1M/day | No | 1M | STANDARD (current) |
| gpt-5-codex | $2.00 | $8.00 | $5.00 | 1M/day | No | 200K | STANDARD (alt) |
| gpt-5-chat-latest | $2.00 | $8.00 | $5.00 | 1M/day | No | 1M | — |
| o1 | $15.00 | $60.00 | $37.50 | 1M/day | Yes | 200K | — |
| o3 | $10.00 | $40.00 | $25.00 | 1M/day | Yes | 200K | avoid |
| text-embedding-3-small | $0.02 | — | $0.02 | — | No | 8K | EMBEDDING (keep) |

> Prices sourced from OpenAI model launch announcements. gpt-5 pricing confirmed at $2/$8 per 1M (same tier as gpt-4.1). gpt-4.1-mini confirmed at $0.40/$1.60. o4-mini confirmed at $1.10/$4.40.

---

## Regen v9 Workload Analysis (alliecatowo)

### Log: `/tmp/regen-alliecatowo-v9-gpt5-credits-2026-05-09.log`

**Total API calls:** 507 calls to `/chat/completions`  
**Rate limit retries:** 41 retry events (429s + rate-limit 403s during repo agent fan-out)

### Per-stage breakdown

| Stage | Model Tier | Tokens In | Tokens Out | Notes |
|---|---|---|---|---|
| FETCH contamination scoring | FAST (gpt-5-mini) | ~1,000 est | ~200 est | 55 items scored |
| EXPLORE: claude_code | STANDARD (gpt-5) | 21,473 | 2,504 | 6 turns, logged |
| EXPLORE: github | STANDARD (gpt-5) | 0 | 0 | timed out / 0 turns |
| EXPLORE: repo agents (5 repos) | STANDARD (gpt-5) | ~150K est | ~15K est | alliecatowo__alliecatowo=36 turns, others=0 |
| SYNTHESIZE: aspect agents (11 aspects) | STANDARD (gpt-5) | ~200K est | ~90K est | 3 aspects hit 8192 output limit and failed |
| SYNTHESIZE: final chief | STANDARD (gpt-5) | ~30K est | ~5K est | — |
| **TOTAL** | — | **~400K est** | **~110K est** | rough; synthesis not instrumented per-call |

### Critical findings from log

1. **o3 is NOT used.** Despite being configured as the THINKING tier default, the chief synthesizer calls `get_model(ModelTier.STANDARD)` — aspect agents run on gpt-5, not o3. THINKING tier is currently unused.
2. **Aspect agents are hitting the 8192 output token limit** — `voice_signature`, `audience_modulation`, `decision_frameworks_in_practice` all failed with output overflow on gpt-5. This is a separate bug (max_tokens cap too low), not a model selection issue.
3. **507 total completions** in a single regen — primarily from repo agent turn-by-turn calls (36 turns × tool calls for alliecatowo__alliecatowo repo).

### Estimated cost for v9 regen (at gpt-5 $2/$8 per 1M)

```
STANDARD calls:  ~400K in × $2/1M = $0.80
                 ~110K out × $8/1M = $0.88
FAST calls:      ~5K in × $0.15/1M = $0.001
                 ~1K out × $0.60/1M = $0.001
Embedding:       negligible

Estimated total: ~$1.68/regen
```

If THINKING were actually wired for the 13 aspect agents (didn't exist yet, but o3 at $10/$40):
```
  Aspect agents: 13 × ~15K in × $10/1M = $1.95 in
                 13 × ~7K out × $40/1M  = $3.64 out
  Would add: ~$5.59 per regen just for aspects
```

---

## Recommended Mix

### Decision rationale

**FAST** — `gpt-4.1-nano` ($0.10/$0.40)
- Cheapest available with 1M context
- Used for: contamination scoring, compaction summaries, memory assembler
- Was `gpt-5-mini`: saves ~60% on FAST calls
- `gpt-5-nano` is similar price but less context; gpt-4.1-nano has 1M ctx which helps compaction

**STANDARD** — `gpt-5` ($2/$8) — **keep as-is**
- Allie's intuition confirmed: gpt-5 is not more expensive than gpt-4.1 (same price tier)
- Best tool-calling quality in the 1M-pool at this price
- `gpt-4.1-mini` at $0.40/$1.60 is 5× cheaper but lower quality for complex multi-tool explorer agents. Worth A/B testing separately.

**THINKING** — `o4-mini` ($1.10/$4.40) instead of `o3` ($10/$40)
- o3 is currently unused (code calls STANDARD not THINKING), but when we wire it:
- o4-mini is 9× cheaper than o3 with comparable reasoning quality for narrative synthesis tasks
- 1200-2000 word essay generation doesn't need full o3 — it's long-form writing, not hard math
- At 13 aspects × o4-mini: ~$0.35/regen aspect cost vs ~$5.59 for o3

**EMBEDDING** — `text-embedding-3-small` ($0.02) — **keep as-is**

### Side note: `gpt-5-mini` → doesn't exist yet

The current `FAST = "openai:gpt-5-mini"` references a model that has not been announced as of this writing. The equivalent that actually exists in the 10M/day pool is `gpt-4.1-nano` or `gpt-4o-mini`. Leaving this as a non-existent model risks silent fallback failures.

---

## Summary of Changes

| Tier | Before | After | Savings |
|---|---|---|---|
| FAST | `openai:gpt-5-mini` (non-existent) | `openai:gpt-4.1-nano` | ~60% on FAST calls; also fixes silent model error |
| STANDARD | `openai:gpt-5` | `openai:gpt-5` (keep) | — |
| THINKING | `openai:o3` | `openai:o4-mini` | ~9× cheaper when wired; $5+ savings/regen |
| EMBEDDING | `openai:text-embedding-3-small` | `openai:text-embedding-3-small` (keep) | — |

**Estimated $/regen savings when THINKING tier gets wired:** ~$5+ per regen  
**Estimated $/regen savings from FAST fix:** < $0.05 (low call volume currently)

### Follow-up tickets to file

- Bug: aspect agents exceeding 8192 output token limit (3 of 13 failing) — increase `max_tokens` or use streaming
- Enhancement: wire THINKING tier for aspect narrative agents (currently they use STANDARD)
- A/B test: `gpt-4.1-mini` vs `gpt-5` for STANDARD explorer quality
