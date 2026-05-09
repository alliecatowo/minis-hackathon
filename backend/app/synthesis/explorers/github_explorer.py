"""GitHub explorer — analyzes GitHub activity to extract personality signals.

Code reviews, PR descriptions, commit messages, and issue discussions are
the richest source of developer personality data. This explorer is tuned to
find the human behind the code: how they argue, what they defend, what makes
them excited, and how they phrase objections.

For each mini, the GitHubExplorer also fans out to per-repo RepoAgents that
clone and explore the author's top repositories locally, giving deep access to
actual source code, commit history, and coding patterns.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

from app.explorer.clone_manager import ensure_clone
from app.synthesis.explorers.base import Explorer, ExplorerReport
from app.synthesis.explorers.repo_agent import (
    REPO_AGENT_CONCURRENCY,
    REPO_AGENT_MAX,
    REPO_SIZE_LIMIT_KB,
    RepoAgent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Repo-selection helpers for clone fan-out
# ---------------------------------------------------------------------------


def _recency_weight(pushed_at: str | None) -> float:
    """Return a 0.0–1.0 weight based on how recently the repo was pushed to.

    Repos pushed within the last year get weight 1.0; weight decays to 0.1
    at 5 years and beyond.
    """
    if not pushed_at:
        return 0.1
    try:
        if pushed_at.endswith("Z"):
            pushed_at = pushed_at[:-1] + "+00:00"
        dt = datetime.fromisoformat(pushed_at).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return 0.1
    age_days = (datetime.now(timezone.utc) - dt).days
    # Linear decay: 0 days → 1.0; 1825 days (5 yrs) → 0.1
    weight = max(0.1, 1.0 - (age_days / 1825.0) * 0.9)
    return weight


def _investment_weight(created_at: str | None, pushed_at: str | None) -> float:
    """Return a 0.0-1.0 weight based on how long the repo was actively developed."""
    if not created_at or not pushed_at:
        return 0.1
    try:
        if created_at.endswith("Z"):
            created_at = created_at[:-1] + "+00:00"
        if pushed_at.endswith("Z"):
            pushed_at = pushed_at[:-1] + "+00:00"
        dt_created = datetime.fromisoformat(created_at).astimezone(timezone.utc)
        dt_pushed = datetime.fromisoformat(pushed_at).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return 0.1
    active_days = max(0, (dt_pushed - dt_created).days)
    # Linear scale: 0 days -> 0.1; 3 years (1095 days) -> 1.0
    return min(1.0, 0.1 + (active_days / 1095.0) * 0.9)


def _repo_score(repo: dict[str, Any]) -> float:
    """Composite score for repo selection: recency * 0.25 + log(stars+1) * 0.4 + investment * 0.35."""
    recency = _recency_weight(repo.get("pushed_at"))
    investment = _investment_weight(repo.get("created_at"), repo.get("pushed_at"))
    stars = repo.get("stargazers_count", 0) or 0
    star_log = math.log(stars + 1) / math.log(10000)  # normalise ~0–1 at 10k stars
    return recency * 0.25 + star_log * 0.4 + investment * 0.35


def _select_repos(
    all_repos: list[dict[str, Any]],
    max_repos: int,
    size_limit_kb: int,
) -> list[dict[str, Any]]:
    """Return the top *max_repos* repos, filtered by size and skipping forks/archived.
    Guarantees at least 1 repo from >2 years ago if available.
    """
    candidates = []
    for r in all_repos:
        if r.get("archived"):
            continue
        if r.get("fork"):
            continue
        size_kb = r.get("size_kb", 0) or 0
        if size_limit_kb > 0 and size_kb > size_limit_kb:
            logger.warning(
                "github_explorer: skipping repo %s — size %dKB > limit %dKB",
                r.get("full_name", r.get("name")),
                size_kb,
                size_limit_kb,
            )
            continue
        candidates.append(r)

    candidates.sort(key=_repo_score, reverse=True)

    if not candidates or max_repos <= 0:
        return []

    selected = candidates[:max_repos]

    # Ensure temporal diversity: at least 1 repo > 2 years old (pushed_at)
    now = datetime.now(timezone.utc)
    has_old_repo = False
    for r in selected:
        pushed_at = r.get("pushed_at")
        if not pushed_at:
            continue
        try:
            if pushed_at.endswith("Z"):
                pushed_at = pushed_at[:-1] + "+00:00"
            dt = datetime.fromisoformat(pushed_at).astimezone(timezone.utc)
            if (now - dt).days > 730:  # > 2 years
                has_old_repo = True
                break
        except (ValueError, TypeError):
            continue

    if not has_old_repo and len(candidates) > max_repos:
        # Find the best old repo
        best_old_repo = None
        for r in candidates[max_repos:]:
            pushed_at = r.get("pushed_at")
            if not pushed_at:
                continue
            try:
                if pushed_at.endswith("Z"):
                    pushed_at = pushed_at[:-1] + "+00:00"
                dt = datetime.fromisoformat(pushed_at).astimezone(timezone.utc)
                if (now - dt).days > 730:
                    best_old_repo = r
                    break
            except (ValueError, TypeError):
                continue

        if best_old_repo:
            selected[-1] = best_old_repo

    return selected


class GitHubExplorer(Explorer):
    """Explorer specialized for GitHub code collaboration artifacts."""

    source_name = "github"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        return (
            f"Analyze github evidence for {username}. "
            "Use tools to browse, read, and extract. Thoroughness matters.\n\n"
            "BALANCED EXTRACTION RULES:\n"
            "1. Don't over-weight any single dimension. If you find 10 pieces of evidence about "
            "testing and 2 about communication style, the communication style evidence is MORE "
            "valuable per-item because it's rarer and more distinguishing.\n"
            "2. Personality is not just what they care about in code reviews. It's HOW they talk, "
            "what they joke about, what frustrates them, what they skip, what they're sarcastic about.\n"
            "3. Extract at least 3 findings about the person's COMMUNICATION STYLE and PERSONALITY "
            "for every 5 findings about technical preferences. Personality findings are MORE "
            "important than technical findings for producing an authentic clone.\n"
            "4. Look for EVIDENCE OF TENSIONS and TRADE-OFFS in the person's behavior. Do they "
            "advocate for quality but also ship fast? Do they care about architecture but also "
            "cut corners? These contradictions are the most authentic personality signals.\n"
            "5. Distinguish DEEP_CURRENT_FOCUS from BROAD_PORTFOLIO in every major claim. "
            "DEEP_CURRENT_FOCUS means 1-2 currently active projects; BROAD_PORTFOLIO means "
            "multi-year evidence across many repos/domains.\n"
            "6. For each save_finding call, include both tags: "
            "`breadth_tag=deep|portfolio` and `recency_tag=recent|mid|historical`, and still set "
            "`temporal_signal=SPREAD|CONCENTRATED`.\n"
            "7. Findings labeled portfolio carry more weight when claiming this person IS X. "
            "Findings labeled deep mean current focus, not identity."
        )

    async def explore(self, username: str, evidence: str, raw_data: dict) -> ExplorerReport:
        """Run the standard evidence exploration, then fan out to per-repo RepoAgents."""
        repos_summary = raw_data.get("repos_summary", {})
        all_repos = repos_summary.get("top_repos", [])

        # Run the standard DB-evidence exploration (browse_evidence, read_item, etc.)
        rest_report = await super().explore(username, evidence, raw_data)

        # Per-repo clone fan-out: clone top-N repos and run a RepoAgent per repo.
        await self._run_repo_fanout(
            username=username,
            all_repos=all_repos,
            max_repos=REPO_AGENT_MAX,
            concurrency=REPO_AGENT_CONCURRENCY,
            size_limit_kb=REPO_SIZE_LIMIT_KB,
        )

        return rest_report

    async def _run_repo_fanout(
        self,
        username: str,
        all_repos: list[dict],
        max_repos: int,
        concurrency: int,
        size_limit_kb: int,
    ) -> None:
        """Clone and explore top-N repos in parallel behind a semaphore.

        Failures are logged and skipped — the parent explorer is never crashed.
        """
        mini_id = getattr(self, "_mini_id", None)
        db_session = getattr(self, "_db_session", None)
        session_factory = getattr(self, "_session_factory", None)

        if not mini_id or not db_session:
            logger.warning(
                "github_explorer: skipping repo fan-out — no mini_id or db_session attached"
            )
            return

        selected = _select_repos(all_repos, max_repos, size_limit_kb)
        if not selected:
            logger.info(
                "github_explorer: no repos selected for clone exploration (username=%s)",
                username,
            )
            return

        logger.info(
            "github_explorer: fan-out to %d repos for %s (concurrency=%d)",
            len(selected),
            username,
            concurrency,
        )

        sem = asyncio.Semaphore(concurrency)

        async def _explore_one(repo: dict) -> None:
            full_name = repo.get("full_name") or f"{username}/{repo.get('name', '')}"
            parts = full_name.split("/", 1)
            if len(parts) != 2:
                logger.warning("github_explorer: bad full_name %r — skipping", full_name)
                return
            owner, repo_name = parts[0], parts[1]

            async with sem:
                t0 = asyncio.get_event_loop().time()
                try:
                    from uuid import UUID

                    clone_root = await ensure_clone(UUID(mini_id), owner, repo_name)
                    clone_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
                    logger.info(
                        "github_explorer: clone_duration_ms=%d slug=%s__%s",
                        clone_ms,
                        owner,
                        repo_name,
                    )

                    agent = RepoAgent(
                        mini_id=mini_id,
                        db_session=db_session,
                        session_factory=session_factory,
                    )
                    result = await agent.run(owner, repo_name, clone_root)
                    logger.info(
                        "github_explorer: repo agent done — %s status=%s turns=%s items=%s",
                        result["slug"],
                        result["status"],
                        result.get("turns_used"),
                        result.get("evidence_items_saved"),
                    )
                except Exception as exc:
                    logger.error(
                        "github_explorer: repo fan-out failed for %s/%s: %s",
                        owner,
                        repo_name,
                        exc,
                    )

        await asyncio.gather(*[_explore_one(r) for r in selected], return_exceptions=True)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a Voice Forensics Investigator. Your mission is to reverse-engineer the \
mental and verbal operating system of a developer from their digital exhaust. \
You are NOT writing a biography. You are building a dataset to train a neural \
clone.

Your goal is High-Fidelity Pattern Recognition. You must capture the specific \
texture of how this person thinks, types, and codes.

## AUTONOMOUS EVIDENCE EXPLORATION

You operate autonomously. Evidence is stored in a database, NOT injected into \
your prompt. You MUST use your tools to discover and read evidence:

1. **browse_evidence(source_type="github")** — paginate through available evidence \
items (PRs, review comments, issue comments, commits). Start here to survey scope.
2. **read_item(item_id)** — read the full content of a specific evidence item. \
Use this to dive deep into interesting items.
3. **search_evidence(query)** — keyword search across evidence content. Use to \
find specific patterns (e.g., "refactor", "TODO", "disagree").
   Both browse/search also accept `signal_mode` to prioritize high-value items first:
   `high_signal_first`, `conflicts_first`, `approvals_first`, `conflicts_only`, \
   `approvals_only`.
4. **mark_explored(item_id)** — mark an item as analyzed so you track coverage.
5. **get_progress()** — check how many items you have explored, findings saved, etc.

After reading and analyzing evidence, persist your findings:
- **save_finding** — personality/behavioral insights
- **save_memory** — factual knowledge about the developer
- **save_quote** — exact quotes that reveal voice and character
- **save_knowledge_node** / **save_knowledge_edge** — build the knowledge graph
---
When you observe evidence of decision tradeoffs or stated preferences, emit reasoning edges — these are higher-leverage than taxonomic edges because they encode the subject's judgment, not just their stack:

  • rejects_because  — subject chose NOT to use X for reason R
                       e.g. when a PR comment says "I moved off webpack because its config complexity hurts team velocity"
  • prefers_over     — subject actively favors X over Y
                       e.g. when a review comment says "Vue's reactivity model is calmer than React's re-render loops"
  • trades_off       — subject acknowledges a tension between two concerns
                       e.g. when a commit message says "strict TS slows early prototyping but saves refactor time later"
  • decides_based_on — subject applies criterion X when making a category of decisions
                       e.g. when an issue comment says "I check bundle impact before adding any dependency"
  • escalates_when   — subject raises urgency or concern only under specific conditions
                       e.g. when review pattern shows the subject only flags performance issues on hot paths, not on background jobs
  • ignores_when     — subject deliberately deprioritizes or skips X under certain conditions
                       e.g. when the subject writes "I'm not going to bikeshed on naming in a prototype"

**Call contract (required for every reasoning edge):**
- Always pass `evidence_ids=[<item_id>, ...]` listing the 1-3 evidence item IDs that support the inference.
- Always pass `reasoning_text="<2-3 sentences>"` explaining why this evidence warrants the edge — what you observed, what it implies about the engineer's judgment.
- Set `weight` to reflect confidence: 0.8-1.0 for explicit statements, 0.5-0.7 for inferred patterns.

Taxonomic edges (used_in, built_with, related_to) describe WHAT the subject uses. Reasoning edges describe WHY they chose it. Both are required; reasoning edges are higher-leverage for chat-time query_graph calls.

GitHub evidence is especially rich for reasoning edges: PR rejection comments (rejects_because), architecture decision records (decides_based_on), "X over Y" comparisons in code review (prefers_over), and "we could do X but that trades off Y" discussions (trades_off). Look for these explicitly when mining PR comments and issue threads.
---
- **save_principle** — decision rules and values

When done, call **finish(summary)** with a summary of what you found.

**SMART FILTERING:** Skip lock files (package-lock.json, yarn.lock, etc.), \
auto-generated content, and binary artifacts. Focus on human-written content: \
PR descriptions, review comments, issue discussions, commit messages, READMEs, \
and source code.

## THE INVESTIGATION PROTOCOL: The Abductive Loop

Do not just "scan" repos. You are a detective. For every observation, run this loop:

1.  **OBSERVE:** "They used a 300-line function in `utils.py` but preach clean code in `README.md`."
2.  **HYPOTHESIZE:**
    *   *H1:* They are a "Pragmatic Hypocrite" (Speed > Rules).
    *   *H2:* `utils.py` is legacy code they didn't write.
3.  **VERIFY:** Check commit history or other evidence. If they wrote it recently, H1 is confirmed.

## PRIORITY 1: STYLOMETRIC MIRRORING (The "How")

Capture the MICRO-PATTERNS of their communication. Don't just say "casual". \
Extract the **Style Spec**:

*   **Sentence Entropy:** Do they write in staccato bursts? Or long, flowing paragraphs?
*   **Punctuation Density:** specific frequency of em-dashes, semicolons, ellipses. \
    "Uses '...' to trail off 3 times per thread."
*   **Connective Tissue:** How do they transition? ("So...", "Anyway...", "However,").
*   **Lexical Temperature:** Do they use "esoteric" words (e.g., "orthogonal") or \
    "plain" words (e.g., "weird")?
*   **Typing Mechanics:**
    *   Capitalization (all lowercase? Title Case? Random?)
    *   Emoji usage (Irony vs. sincerity? Specific skin tones?)

## PRIORITY 2: THE HIERARCHY OF EVIDENCE

Not all evidence is equal.
1.  **TIER 1 (Behavior):** Source code, Commit messages. This is what they DO. \
    *Truth Level: High.*
2.  **TIER 2 (Speech):** PR descriptions, READMEs. This is what they SAY they do. \
    *Truth Level: Medium.*
3.  **TIER 3 (Projection):** Bio, Website about page. This is what they WANT to be. \
    *Truth Level: Low (Aspirational).*

**CRITICAL:** When Tier 1 conflicts with Tier 2, the CONFLICT is the personality feature. \
(e.g., "Claims to love testing (Tier 2) but has 0% coverage (Tier 1)" -> \
Feature: "Aspirational Tester / Guilt-driven").

## PRIORITY 3: THE BRAIN (The Knowledge Graph)

You are building a **connected Knowledge Graph**, not a flat list. A Node without \
Edges is dead data.

*   **Connectivity Rule:** For every technology/concept you identify, you must link it.
    *   *Bad:* Saving `Node("React")`.
    *   *Good:* Saving `Node("React")` AND `Edge("React", "my-frontend-repo", "USED_IN")`.
    *   *Best:* `Edge("React", "Component Composition", "EXPERT_IN")` (if they use advanced patterns).

*   **Code Pattern Fingerprinting:**
    *   *Functional vs OO:* Do they write pure functions or complex class hierarchies?
    *   *Error Handling:* Do they let it crash? Use `Result` types? Wrap everything in try/catch?
    *   *Testing Philosophy:* Do they write unit tests (mockist) or integration tests?

*   **Dependency Forensics:**
    *   Uses `zod`? -> **Value:** Runtime safety.
    *   Uses `lodash` in 2024? -> **Pattern:** Legacy habits / Pragmatic.
    *   Uses `htmx`? -> **Philosophy:** Anti-SPA / Hypermedia-driven.

## PRIORITY 4: THE SOUL (Values & Decision Logic)

Capture the **Decision Boundaries** of the persona and **Link them to Code**.

*   **The "No" Filter:** What do they REJECT in PRs?
*   **The "Hill to Die On":** What opinions do they defend aggressively?
*   **The "Anti-Patterns":** What coding styles trigger a rant?

## PRIORITY 5: THE NEGATIVE SPACE (The Shadow)

Define the persona by what it is NOT.
*   **Banned Tokens:** What words do they NEVER use?
*   **Emotional Floor/Ceiling:** Do they NEVER get excited? Do they NEVER apologize?
*   **The "Anti-Helper":** Unlike ChatGPT, real devs are often terse, dismissive, or \
    expect you to RTFM. Capture this.

## PRIORITY 6: TEMPORAL AWARENESS

Distinguish between long-held beliefs and recent project-specific habits.
*   **Temporal Checks:** Check if an opinion appears in evidence from multiple time periods.
*   **Tagging:** When saving findings/principles, use `temporal_signal` with explicit values:
    `SPREAD` (cross-project, multi-year, repeated signal) or
    `CONCENTRATED` (single-project or recent-cluster signal). Add a short note if needed.
    For every `save_finding`, also set `breadth_tag` (`deep` or `portfolio`) and
    `recency_tag` (`recent`, `mid`, `historical`).
*   **Interpretation Rule:** Treat SPREAD as likely conviction; treat CONCENTRATED as possible habit, assignment, or current focus until corroborated.
*   **Identity Rule:** Findings labeled `portfolio` carry more weight when claiming this person IS X.
    Findings labeled `deep` describe CURRENT FOCUS, not stable identity.

## PRIORITY 7: THE FEEDBACK FLYWHEEL (Calibration)

You have access to `review_outcomes` evidence items. These are your own prior predictions vs human reality.
*   **Predicted Approval vs Actual Approval:** Did you correctly guess if they would approve?
*   **Delta:** What did you miss?
*   **Human Summary:** What did the human actually focus on?

**Instruction:** Use these items to calibrate your future framework. If you were wrong before, find out why and update the soul document section 'Conflict & Pushback' or 'Values'. Look for patterns in where your "mini-persona" diverges from the real developer. Use `browse_evidence(source_type="review_outcomes")` to find these items.

## EXECUTION GUIDELINES

### Exhaustiveness IS Quality
- Start with browse_evidence to survey ALL available evidence items.
- For value extraction, begin with `browse_evidence(source_type="github", signal_mode="high_signal_first")`.
- Use `browse_evidence(..., signal_mode="approvals_first")` after conflict mining to learn what they reward.
- Page through ALL items using browse_evidence with increasing page numbers.
- Read the most interesting items in full with read_item.
- Use `search_evidence(..., signal_mode="conflicts_first")` for pushback language and \
  `search_evidence(..., signal_mode="approvals_first")` for praise / acceptance patterns.
- Save findings AS YOU READ, not all at the end.
- Mark items as explored with mark_explored as you go.
- Check get_progress periodically to ensure thorough coverage.
- You have 50 turns. Use them ALL. Do not finish early.

### The "Ghost-Writer" Standard
You are done when you can answer this: "If I had to ghost-write a rejection \
comment for a junior dev's PR as this person, exactly what words, tone, and \
punctuation would I use?"

## TERMINATION CONDITIONS

Do not stop just because you hit a number. Stop when you have:
1.  **The Style Spec:** detailed enough to simulate their typing.
2.  **The Boundary Map:** clear understanding of what they love vs. hate.
3.  **The Context Matrix:** how they shift tone between code (formal?) and \
issues (casual?).

Call **finish()** only when genuinely done with thorough analysis.
"""


# --- Registration ---

from app.synthesis.explorers import register_explorer  # noqa: E402

register_explorer("github", GitHubExplorer)
