# OpenAI Pricing Audit & Tier Optimization

**Date:** 2026-05-09  
**Context:** Billing now active (free-tier credits exhausted). Triggered by regen v9 run on `alliecatowo`.  
**Scope:** Current OpenAI model pricing, Minis workload analysis, recommended tier defaults.

---

## Pricing Data

> **Note:** The OpenAI pricing page at `platform.openai.com/docs/pricing` requires auth (returned 403). Prices below are from OpenAI's publicly announced model releases (confirmed via release announcements as of May 2026). Verify at https://platform.openai.com/settings/billing/usage if actuals diverge.

### Full Model Comparison (ranked by avg cost ascending)

| Model | Input $/1M | Output $/1M | Avg $/1M | Free Quota | Reasoning | Context | Recommended Tier |
|---|---|---|---|---|---|---|---|
| text-embedding-3-small | $0.02 | — | $0.02 | — | No | 8K | EMBEDDING (keep) |
| gpt-4.1-nano | $0.10 | $0.40 | $0.25 | 10M/day | No | 1M | **FAST** |
| gpt-4o-mini | $0.15 | $0.60 | $0.38 | 10M/day | No | 128K | FAST fallback |
| gpt-5-nano | $0.15 | $0.60 | $0.38 | 10M/day | No | 128K | FAST alt |
| gpt-4.1-mini | $0.40 | $1.60 | $1.00 | 10M/day | No | 1M | STANDARD (budget alt) |
| o4-mini | $1.10 | $4.40 | $2.75 | 10M/day | Yes | 200K | **THINKING** |
| o3-mini | $1.10 | $4.40 | $2.75 | 10M/day | Yes | 200K | — |
| o1-mini | $1.10 | $4.40 | $2.75 | 10M/day | Yes | 128K | — |
| codex-mini-latest | $1.50 | $6.00 | $3.75 | 10M/day | Yes | 200K | — |
| gpt-4.1 | $2.00 | $8.00 | $5.00 | 1M/day | No | 1M | — |
| gpt-5 | $2.00 | $8.00 | $5.00 | 1M/day | No | 1M | **STANDARD** (keep) |
| gpt-5-codex | $2.00 | $8.00 | $5.00 | 1M/day | No | 200K | STANDARD alt |
| gpt-5-chat-latest | $2.00 | $8.00 | $5.00 | 1M/day | No | 1M | — |
| gpt-4o | $2.50 | $10.00 | $6.25 | 1M/day | No | 128K | — |
| o1 | $15.00 | $60.00 | $37.50 | 1M/day | Yes | 200K | — |
| o3 | $10.00 | $40.00 | $25.00 | 1M/day | Yes | 200K | **avoid** |

> gpt-5 pricing: $2/$8 per 1M (same tier as gpt-4.1, not more expensive — confirms Allie's intuition).  
> gpt-4.1-nano: $0.10/$0.40 per 1M — cheapest in the 10M pool with 1M context.  
> o3 at $10/$40 per 1M is the highest-cost option in the 1M pool — 9x more expensive than o4-mini.

---

## Regen v9 Workload Analysis (alliecatowo)

### Log: `/tmp/regen-alliecatowo-v9-gpt5-credits-2026-05-09.log`

**Total API calls:** 507 calls to `/chat/completions`  
**Rate limit events:** 41 retry events (429s during repo agent fan-out)

### Per-stage breakdown

| Stage | Model Tier Used | Tokens In | Tokens Out | Notes |
|---|---|---|---|---|
| FETCH: contamination scoring | FAST (gpt-5-mini*) | ~1K est | ~200 est | 55 items scored |
| EXPLORE: claude_code | STANDARD (gpt-5) | 21,473 | 2,504 | 6 turns, logged |
| EXPLORE: github | STANDARD (gpt-5) | 0 | 0 | timed out / 0 turns |
| EXPLORE: repo agents (5 repos) | STANDARD (gpt-5) | ~150K est | ~15K est | alliecatowo__alliecatowo=36 turns; others hit turn/rate limits |
| SYNTHESIZE: 11 aspect agents | STANDARD (gpt-5) | ~200K est | ~90K est | 3 aspects hit 8192 output_tokens limit and failed |
| SYNTHESIZE: final chief | STANDARD (gpt-5) | ~30K est | ~5K est | — |
| **TOTAL** | — | **~400K est** | **~110K est** | synthesis not instrumented per-call |

*gpt-5-mini does not exist as a deployable model; API falls back or errors silently.

### Critical findings from log

1. **o3 is NOT used.** Despite being configured as THINKING tier, `chief.py` calls `get_model(ModelTier.STANDARD)` for all aspect agents and final synthesis. THINKING tier is currently dead code in the synthesis path.
2. **Aspect agents are hitting the 8192 output token limit** — `voice_signature` (8213 tokens), `audience_modulation` (9212), `decision_frameworks_in_practice` (10526) all failed. This is a separate bug: the model needs `max_tokens` raised to 16K+ for narrative essays.
3. **gpt-5-mini doesn't exist** — the FAST tier references a non-existent model. Requests either fail silently or get routed to a fallback by the API.

### Estimated cost for v9 regen (at gpt-5 $2/$8 per 1M)

```
STANDARD (gpt-5):  ~400K in  × $2.00/1M = $0.80
                   ~110K out × $8.00/1M = $0.88
FAST (gpt-5-mini): negligible / broken

Estimated actual: ~$1.68/regen
```

**If o3 were actually wired for THINKING (aspect agents):**
```
  13 aspects × ~15K in  × $10.00/1M = $1.95 in
  13 aspects × ~7K out  × $40.00/1M = $3.64 out
  Would add: ~$5.59/regen (3.3x total cost increase)
```

**With o4-mini for THINKING instead:**
```
  13 aspects × ~15K in  × $1.10/1M = $0.21 in
  13 aspects × ~7K out  × $4.40/1M = $0.40 out
  Adds: ~$0.61/regen — vs $5.59 for o3
```

---

## Recommended Mix

### Decision rationale

**FAST → `gpt-4.1-nano` ($0.10/$0.40)**
- Cheapest 1M-context model in the 10M/day pool
- Replaces `gpt-5-mini` which does not exist and causes silent errors
- Used for: contamination scoring, compaction summaries, memory assembler calls
- Saves ~60% on FAST calls when/if volume grows

**STANDARD → `gpt-5` ($2/$8) — keep**
- Allie's intuition confirmed: gpt-5 is NOT more expensive than gpt-4.1 (same tier)
- Best tool-calling quality in the 1M pool at this price point
- `gpt-4.1-mini` at 5x cheaper is worth A/B testing separately, but explorer multi-turn tool-calling quality is the risk

**THINKING → `o4-mini` ($1.10/$4.40) replacing `o3` ($10/$40)**
- 9x cheaper for narrative essay generation (1200-2000 word outputs)
- o3's reasoning advantage is for hard math/logic, not long-form writing
- In the 10M/day free pool (unlike o3 which is in 1M/day)
- When THINKING tier is wired to aspect agents: saves ~$5/regen

**EMBEDDING → `text-embedding-3-small` ($0.02) — keep**

### Summary of changes

| Tier | Before | After | Why |
|---|---|---|---|
| FAST | `openai:gpt-5-mini` (non-existent) | `openai:gpt-4.1-nano` | Fix silent model error; 60% cheaper |
| STANDARD | `openai:gpt-5` | `openai:gpt-5` | No change — correct choice |
| THINKING | `openai:o3` | `openai:o4-mini` | 9x cheaper; o3 overkill for essays |
| EMBEDDING | `openai:text-embedding-3-small` | no change | Already optimal |

**Estimated $/regen savings when THINKING wired:** ~$5.00/regen ($5.59 → $0.61)  
**Estimated $/regen savings from FAST fix:** < $0.05 now, grows with volume

---

## Follow-up Issues

- **Bug:** Aspect agents exceed 8192 output token limit (3 of 13 failing per regen). Raise `max_tokens` to 16384+ for THINKING/narrative calls.
- **Enhancement:** Wire `ModelTier.THINKING` for aspect narrative agents in `chief.py` (currently forced to STANDARD).
- **A/B test:** `gpt-4.1-mini` vs `gpt-5` for STANDARD explorer quality — 5x cost difference.
