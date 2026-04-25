# Fidelity Eval — CI Gate & Local Usage

## What it measures

The fidelity eval sends golden-turn prompts to live mini chat endpoints and LLM-judges each response against:

- **Overall score** (1–5): holistic answer quality
- **Voice score**: does it sound like the real person?
- **Factual score**: are project/tech facts correct?
- **Framework score**: does it apply the person's decision patterns?
- **Agreement scorecard** (when a held-out review is present): blocker/comment precision, recall, F1; verdict match

Subjects: `alliecatowo`, `jlongster`, `joshwcomeau`.

## PR comment

When a PR touches `backend/app/synthesis/**`, `backend/eval/**`, or `backend/app/review_cycles.py`, the `Fidelity Eval` workflow posts (or updates) a sticky bot comment with:

- Per-subject score tables
- Delta from the last baseline (≥2 pp change is highlighted)
- Rubric breakdown per turn

The job is **non-blocking** — it will never prevent a merge. A regression surfaces as a visible yellow annotation, not a red gate. Once the eval stabilises we'll flip `continue-on-error: false`.

## Running locally

```bash
# 1. Start the backend (in a separate terminal)
cd backend
uv run uvicorn app.main:app --reload

# 2. Run the eval
cd backend
uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo,jlongster,joshwcomeau \
  --base-url http://localhost:8000 \
  --out eval-report.md

# 3. Compare against a prior run (regression detection)
uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo \
  --prior eval-report.json \   # previous run's JSON output
  --out eval-report-new.md
```

The script writes two files side-by-side:
- `eval-report.md` — human-readable Markdown (same content as the PR comment)
- `eval-report.json` — machine-readable; use as `--prior` on the next run

Exit code `2` means a regression > 0.3 overall average points was detected when `--prior` is provided.

## Live Review Predictor Contract

`backend/tests/test_live_review_predictor_contract.py` is a gated live LLM contract for the review predictor no-fallback path. It is skipped unless explicitly enabled and a provider key is present:

```bash
cd backend
RUN_LIVE_LLM_CONTRACT_TESTS=true \
DEFAULT_PROVIDER=gemini \
GEMINI_API_KEY=... \
REVIEW_PREDICTOR_LLM_MAX_TURNS=2 \
REVIEW_PREDICTOR_LLM_REQUEST_TOKEN_LIMIT=12000 \
REVIEW_PREDICTOR_LLM_RESPONSE_TOKEN_LIMIT=2048 \
REVIEW_PREDICTOR_LLM_TOTAL_TOKEN_LIMIT=14000 \
uv run pytest tests/test_live_review_predictor_contract.py -m live_llm -vv -rs
```

Without `RUN_LIVE_LLM_CONTRACT_TESTS=true`, pytest reports the skip reason. With the gate enabled, the contract accepts either a valid `review_prediction_v1` artifact from the real LLM path or an explicit `mode="gated"` unavailable artifact. It rejects the deterministic `local_smoke` fallback path.

## Required secrets (CI)

Configure these in **Settings → Secrets and variables → Actions**:

| Secret | Purpose | Required |
|---|---|---|
| `GEMINI_API_KEY` | Judge model + mini LLM | Yes |
| `DATABASE_URL` | PostgreSQL connection for local backend | Yes (unless `FLY_EVAL_URL` set) |
| `SERVICE_JWT_SECRET` | Mint eval bearer tokens; must match backend | Yes (unless `DEV_AUTH_BYPASS=true`) |
| `FLY_EVAL_URL` | Hosted backend URL; skips local backend startup | Optional |

`GITHUB_TOKEN` is injected automatically by Actions and needs no manual configuration.

The separate `Live LLM Contract` workflow is manual by default. Nightly runs require `ENABLE_NIGHTLY_LIVE_LLM_CONTRACTS=true` as an Actions variable plus one provider key (`GEMINI_API_KEY` or `GOOGLE_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`). The workflow prints gate diagnostics before running pytest and applies the same small predictor token caps shown above.

## Baseline caching strategy

The workflow caches `eval-baseline.json` under the key `fidelity-eval-baseline-main-<run_id>`, restored by prefix `fidelity-eval-baseline-`. On every scheduled daily run (and on merges to main) the cache is overwritten with the latest report. PR runs restore the most recent baseline and pass it as `--prior` to surface deltas.
