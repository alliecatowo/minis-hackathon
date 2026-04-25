# Minis Archaeology Report

> **Date:** 2026-04-20
> **Purpose:** Excavate design thinking, research, and prompt engineering from previous Minis attempts that never made it into the current codebase.
> **Scope:** Read-only survey of previous repos and Claude session transcripts.

---

## Sources Surveyed

### Previous Repositories

| Repo | Path | Description | Key Artifacts Found |
|---|---|---|---|
| `baby-allie-hatchling` | `/home/Allie/develop/baby-allie-hatchling/` | ML research project — meta-learned Hebbian plasticity for LLMs (BDH fork). Not directly Minis-related but contains neuroscience-grounded architecture thinking. | `docs/pdd.md`, `docs/tdd.md`, `docs/roadmap.md` |
| `minis-v2` | `/home/Allie/develop/minis-v2/` | Second Minis attempt. Full pipeline: GitHub ingestion → DuckDB → value extraction → spirit synthesis → ORPO fine-tuning with LoRA/DoRA adapters. | `minis/distill/values.py`, `minis/distill/spirit.py`, `minis/amplify/evol.py`, `minis/amplify/judge.py`, `minis/amplify/simulator.py`, `minis/train/config.py`, `minis/ingest/query.py` |
| `my-minis` | `/home/Allie/develop/my-minis/` | Third attempt. Multi-agent LangGraph pipeline with specialized sub-agents: `PersonalityTypologistAgent` (MBTI/Big Five/Enneagram), `BehavioralContextAgent` (context-aware), `SynthesisAgent` (Gemini Thinking), `AIDetectionAgent`. Most sophisticated personality schema of any attempt. | `packages/minis/agents/`, `packages/minis/domain/services/`, `frontend/content/3.blog/` |
| `minis-hackathon` (then-current workspace) | `/home/Allie/develop/minis-hackathon/` | Historical repo/workspace name at archaeology time. Docs and `.claude/` subdirs only scanned. | `docs/research.md`, `docs/brain_architecture_proposal.md`, `docs/VISION.md`, `docs/ADR_001_UNIFIED_GRAPH_MEMORY.md` |

### Claude Code Session Transcripts

| Project | Sessions Found | Notes |
|---|---|---|
| `minis-hackathon` | 26 sessions (2 with .jsonl > 3MB) | Key sessions: `ff4c3ddc` (April 14-15 deep push, brainstorm at line 160), `da921814` (ongoing) |
| `minis-v2` | 17 session dirs (subagents only, no top-level .jsonl) | Contains LoRA serving research, vLLM multi-LoRA patterns, ORPO training implementation, RunPod deploy agents |
| `baby-allie-hatchling` | 8 session dirs (subagents only) | ML infrastructure (not directly Minis-applicable) |

---

## Per-Source Inventory

### `baby-allie-hatchling`

A separate research project forking Pathway's BDH (post-Transformer Hebbian plasticity model). Technically orthogonal to Minis, but surfaced:
- Meta-learned plasticity as a framing for "how to learn" vs "what to learn" — maps conceptually to the difference between extracting someone's decision *process* vs their past decisions.
- Rigorous phased-gate development process (PDD + TDD + Roadmap trinity) worth borrowing for Minis feature development discipline.
- Neuromodulation analogy: biological brains use dopamine/acetylcholine to adjust *how aggressively* synapses update. This is the model for "context-dependent adaptation" — a person reviews differently when stressed vs relaxed, when reviewing juniors vs seniors.

### `minis-v2`

The most technically ambitious previous attempt. Key systems:

**Conflict-Evidence Mining** (`minis/distill/values.py`): Values are revealed in conflict. A dedicated `ValueExtractor` queries DuckDB for `CHANGES_REQUESTED` reviews, disagreement signals, pushback patterns. The insight: "conflict encourages individuals to search for attributions, exposing true decision heuristics." This principle is partially in the current `principles_json` but the *querying logic* is far more sophisticated here — keyword patterns for disagreement (`"I disagree"`, `"I don't think"`, `"actually,"`, `"blocking"`, `"nit:"`) are hardcoded as gold filters.

**ORPO + DoRA Fine-Tuning** (`minis/train/`): Complete training pipeline — `ORPOTrainer` on top of TRL, `DoRA` (weight-decomposed LoRA) for style learning, `Qwen2.5-1.5B-Instruct` as base model, RunPod GPU deployment. Includes a `QualityJudge` that runs an LLM-as-judge Turing test comparing generated responses against real samples (style_match, authenticity, distinctiveness scores). This was abandoned but the judge design is reusable.

**Evol-Instruct Operators** (`minis/amplify/evol.py`): 6 mutation operators for synthetic training data generation: `DEEPEN` (add hidden bugs), `COMPLICATE` (add requirements), `CONCRETIZE` (specify libraries), `SWITCH_STACK` (change tech), `ADD_CONSTRAINT` (add limits), `MAKE_AMBIGUOUS` (realistic ambiguity). These would generate diverse evaluation scenarios for the review-prediction accuracy harness.

**PairGenerator / Spirit Simulator** (`minis/amplify/simulator.py`): Generates `(chosen, rejected)` ORPO pairs. "Chosen" = response from spirit.md system prompt (the mini). "Rejected" = intentionally bad "generic assistant" responses (formal, verbose, starts with "Great question!"). The contrast is the training signal. **This is the DPO dataset generator that exists as a branch in minis-hackathon but was never merged with a working spirit.md.**

**Conflict Query Patterns** (`minis/ingest/query.py`): `get_conflicts()` and `get_approvals()` — rich DuckDB queries that filter by approval-signal keywords and disagreement-signal keywords. The approvals query captures what the developer considers *good* (which is as revealing as what they reject).

**vLLM Multi-LoRA Research** (from session `d24022b8`): Text-to-LoRA (T2L) approach — generating task-specific adapters from natural language descriptions (a hypernetwork that produces LoRA weights from a constitutional description). This means a mini's soul document could directly produce a LoRA adapter without requiring preference pair training data.

### `my-minis`

The most architecturally sophisticated attempt. Key systems:

**Personality Typologist Agent** (`packages/minis/agents/personality_typologist_agent.py`): Full MBTI inference (questionnaire-guided chain-of-thought, "PsyCoT" methodology), Big Five trait scoring (O/C/E/A/N on 0-1 scale), Enneagram with wing inference, DISC and Socionics cross-validation. Each dimension scored from 3 key behavioral items with evidence citations. Cross-validation: `MBTI I ↔ Big Five low E`, `T ↔ low A`, `J ↔ high C`. **This entire agent does not exist in the current pipeline.**

**Behavioral Context Agent** (`packages/minis/agents/behavioral_context_agent.py`): Context-aware behavior analysis — how behavior shifts by *audience* (juniors, seniors, stakeholders, peers, maintainers), *collaboration surface* (PR reviews, issues, code discussions, docs, commits), *formality triggers*, *tone modulation* by situation (urgent prod bug vs feature brainstorm vs positive review vs needs-work review vs disagreement vs teaching), *emoji patterns by context*. **Also absent from current pipeline.**

**AI Detection Agent**: Detects AI-assisted vs human-authored content in commits/reviews. Identifies "AI-contamination" of the training corpus. The current pipeline ingests everything without filtering — this agent would dramatically improve soul document quality by distinguishing authentic voice from AI-slop that crept into the user's own output.

**Emergent Role Discovery** (`packages/minis/agents/README_SYNTHESIS.md`): Rather than assigning predefined roles, the synthesis agent discovers emergent roles from behavioral patterns ("Quality Guardian", "Velocity Optimizer", "Architecture Steward"). The current chief synthesizer writes an Identity section but doesn't do structured role inference.

**Formality Matrix** (`packages/minis/agents/schemas.py`): Structured field `communication_profiles.formality_matrix` — separate formality levels by OSS, internal, junior, senior audiences. The current system prompt has a flat communication style section.

**Decision Heuristics** (`packages/minis/agents/schemas.py`): Structured `decision_heuristics` with `fast_approval_triggers`, `slow_review_triggers`, `rejection_triggers` — exactly the "review function" described in VISION.md §Thesis.

**Multi-Collection Qdrant Schema** (`packages/minis/docs/multi_collection_schema.md`): 5-collection vector store design: PR approvals, PR rejections, PR comments, values/principles, code snippets — each with rich metadata and separate embedding strategies. More sophisticated than current flat evidence → pgvector approach.

**Two Blog Posts** (`frontend/content/3.blog/`): "Why We're Building Minis.me" and "How AI Shadows Learn Your Code Review Style" — polished, linkable, explain the product narrative. "73% fewer PR iterations before merge, 2.5x faster time-to-merge, 60% reduction in review burden" — early beta claims that should be validated or cited carefully.

### `minis-hackathon` Docs (`.claude/`, `docs/`)

**`docs/research.md`** (Feb 9, 2026): Comprehensive research doc covering: Stanford Generative Agents benchmark (85% accuracy from 2-hour interviews), TwinVoice benchmark (6 dimensions), "Sideloading" 3-tier fact hierarchy (core facts always in prompt / long-term memory via RAG / historical facts for extraction only), Anthropic Persona Vectors (personality is compositional and decomposable), CDR framework (Kahneman System 1/2 dynamic routing), PersonaChat lineage. **This doc exists in the repo but was never fully ingested into the pipeline design.**

**`docs/brain_architecture_proposal.md`**: Proposes moving from flat Markdown memory to a Developer Knowledge Graph (entities: Technology, Project, Pattern, Opinion, Experience; edges: USES, EXPERT_IN, PREFERS, DISLIKES, ABOUT). Three specialized extractors: `TechStackExplorer` (deterministic package file parsing), `PatternExplorer` (LLM code style analysis), `OpinionMiner` (subjective statement extraction). Includes three gold prompts: "Code Taste Analyst", "War Story Miner", "Opinionated Engineer".

**`docs/ADR_001_UNIFIED_GRAPH_MEMORY.md`**: Proposes Semantic-Episodic Graph (nodes: Concept, Episode, Principle; edges: Semantic, Episodic, Causal). BDI (Belief-Desire-Intention) mapping: values = Principle subgraph, traits = Attribute nodes, style = Pattern nodes linked to Context nodes.

**Key brainstorm (session `ff4c3ddc`, line 160)**: User voice-mode transcript articulating the core architecture shift: "Stop building a brittle harness... I want to give it tools, the read-to-database, write-the-database, the evidence, as a tool, and that's it... I don't want to program in compaction. I want it to just work." This is the genesis of the current autonomous-agent architecture that was subsequently implemented.

---

## Top 10 Extractable Ideas

### Idea 1: Personality Typologist Agent (MBTI / Big Five / Enneagram inference)
**Source:** `my-minis/packages/minis/agents/personality_typologist_agent.py`

A dedicated explorer agent that infers MBTI type, Big Five (OCEAN) scores, and Enneagram type from behavioral evidence using questionnaire-guided chain-of-thought (PsyCoT). Dimension-by-dimension: E/I from collaboration frequency and PR comment patterns; S/N from concrete-vs-abstract focus in code reviews; T/F from review tone and conflict resolution style; J/P from commit patterns and documentation approach. Cross-validates MBTI with Big Five (I↔low E, T↔low A, J↔high C).

**Why it matters:** The personality_typology output becomes a structured scaffold for the soul document. Instead of the chief synthesizer guessing at personality from raw findings, it gets scored coordinates in a validated psychological space. Users can see "INTJ, Big Five: O=0.85 C=0.75 E=0.30" as legible output. Downstream: personality-aware retrieval (retrieve differently for high-A vs low-A reviewers), better comparison across minis.

**Priority: P1** — File ticket.

---

### Idea 2: Behavioral Context Agent (context-dependent communication mapping)
**Source:** `my-minis/packages/minis/agents/behavioral_context_agent.py`

Maps how communication style shifts across audience (juniors vs seniors vs stakeholders vs maintainers), collaboration surface (PR reviews vs issues vs commit messages), urgency (prod bug vs brainstorm), and sentiment valence (approving vs requesting changes vs teaching). Outputs a structured `formality_matrix` and `tone_modulation` table.

**Why it matters:** The current soul document has a single flat "communication style" section. Real engineers shift register dramatically. A mini that sounds the same when praising junior code as when blocking a security vulnerability is unconvincing. The formality matrix makes the mini's context-switching behavior explicit and programmable.

**Verbatim from agent prompt:**
> "Document context-dependent communication patterns: audience-specific behaviors (juniors, seniors, stakeholders), formality triggers, tone modulation by situation (urgent_production_bug, feature_brainstorming, code_review_needs_work, disagreement, teaching), emoji patterns by context."

**Priority: P1** — File ticket.

---

### Idea 3: Conflict-Signal Query Patterns as Gold Filters
**Source:** `minis-v2/minis/distill/values.py` (lines 1-50), `minis-v2/minis/ingest/query.py`

The `get_conflicts()` function filters GitHub interactions using hardcoded disagreement-signal keywords: `CHANGES_REQUESTED` reviews, plus body patterns `"I disagree"`, `"I don't think"`, `"actually,"`, `"should be"`, `"prefer"`, `"rather than"`, `"concerned"`, `"blocking"`, `"nit:"`. Symmetrically, `get_approvals()` filters for `"LGTM"`, `"looks good"`, `"love this"`, `"good catch"`, `"elegant"`.

**Why it matters:** The current GitHub explorer browses evidence without prioritizing conflict/approval signal. Adding a `search_evidence` filter mode that surfaces these gold signals first would dramatically improve value extraction per token. Conflicts reveal true heuristics; approvals reveal true standards.

**Priority: P1** — Enrich existing GitHub explorer with conflict-signal priority querying.

---

### Idea 4: ORPO + DoRA Fine-Tuning Pipeline
**Source:** `minis-v2/minis/train/config.py`, `minis-v2/minis/train/orpo.py`, `minis-v2/minis/amplify/simulator.py`

A complete pipeline for training a mini-specific LoRA adapter: (1) PairGenerator uses soul document as system prompt to generate "chosen" responses; (2) baseline assistant prompt generates contrasting "rejected" responses; (3) QualityJudge runs Turing test (style_match, authenticity, distinctiveness 0-1); (4) ORPOTrainer fine-tunes Qwen2.5-1.5B with DoRA-enabled LoRA; (5) adapter served via vLLM with dynamic load/unload.

**Why it matters:** Fine-tuned adapters produce minis that cannot be prompted out of character. The soul document approach works but has prompt-injection attack surface and context-window limits. A tiny (1.5B) fine-tuned adapter is self-hostable, offline-capable, and essentially impossible to jailbreak out of the persona.

**Note:** User said "no LoRA/fine-tuning" as a principle. **This should be filed as P3** — architectural option for enterprise tier where data privacy and persona strength are paramount, not the default path.

**Priority: P3** — Archive for later (enterprise tier consideration).

---

### Idea 5: Evol-Instruct Operators for Review Scenario Generation
**Source:** `minis-v2/minis/amplify/evol.py`

Six mutation operators: `DEEPEN` (add hidden bugs/race conditions), `COMPLICATE` (add edge cases), `CONCRETIZE` (specify libraries), `SWITCH_STACK` (change language/framework), `ADD_CONSTRAINT` (time/memory limits), `MAKE_AMBIGUOUS` (realistic underspecification). Applied to seed code review scenarios to generate a diverse evaluation set.

**Why it matters:** The review-prediction accuracy metric (ALLIE-382, ALLIE-425) needs a diverse evaluation harness. Evol-Instruct generates novel scenarios the mini has never seen, testing genuine generalization rather than retrieval of similar examples. "The mini that predicts your review with 87% agreement" needs scenarios outside the training distribution.

**Priority: P2** — Needed for evaluation harness, not blocking current shipping.

---

### Idea 6: LLM-as-Judge Style Authenticity Scorer
**Source:** `minis-v2/minis/amplify/judge.py`

A `QualityJudge` that runs LLM-as-judge against 3 dimensions: `style_match` (does it use similar phrasing, vocabulary, structure?), `authenticity` (does it sound human, not obviously AI?), `distinctiveness` (is it distinct from generic "helpful assistant" responses?). Filters out AI-isms like "I'd be happy to help" and over-formal structure. Threshold 0.7+ to accept.

**Why it matters:** Current soul document quality is assessed qualitatively by humans. An automated style-authenticity scorer would enable continuous evaluation and regression testing as the pipeline improves. Could also be surfaced in the UI: "Mini authenticity score: 87%."

**Verbatim judge criteria:**
> "Does it avoid telltale AI phrases like 'I'd be happy to help' or 'Great question!'? Is it distinct from a generic assistant? Does it use domain-specific language the person uses?"

**Priority: P2** — File ticket for automated soul quality scoring.

---

### Idea 7: AI Contamination Detection
**Source:** `my-minis/packages/minis/agents/` (ai_detection_agent.py — confirmed to exist)

An agent that analyzes GitHub content (PR descriptions, issue comments, commit messages) to detect AI-generated vs human-authored text. Outputs: `ai_detection_confidence` (0-1), `ai_usage_contexts` (where AI was likely used), `ai_common_phrases` list (phrases to exclude from authentic voice extraction).

**Why it matters:** Developers increasingly use AI assistants to write PR descriptions and issue responses. If a mini ingests "I'd be happy to help with that" from an AI-assisted PR description as authentic voice, it degrades soul quality. Filtering AI contamination from the corpus before value extraction would improve signal-to-noise dramatically.

**Priority: P1** — Should be added as a pre-processing step in the GitHub explorer.

---

### Idea 8: War Story Miner Prompt
**Source:** `minis-hackathon/docs/brain_architecture_proposal.md`

A specific prompt for extracting "war stories" — evidence of difficult debugging, performance optimization, or major refactors — from commit messages and PR descriptions:

> "Ignore: 'fix typo', 'update deps', 'feature add'. Target: 'tracked down memory leak', 'refactored auth flow', 'migrated database', 'fixed race condition'. Extract: topic, context, summary, complexity_score, evidence_quote."

**Why it matters:** War stories are the highest-value memory entries. They reveal how the developer handles adversity, what complexity level they operate at, and what they're proud of. The current explorer extracts generic findings but doesn't specifically target these high-value signals.

**Priority: P2** — Add as an explorer finding category and targeted search pattern.

---

### Idea 9: Sideloading Three-Tier Fact Hierarchy
**Source:** `minis-hackathon/docs/research.md` (section 1.4), citing LessWrong "Sideloading" technique

Three-tier organization for personality data injection:
1. **Core facts** (always in system prompt): values, communication style, decision patterns, technical philosophy — never evicted
2. **Long-term memory** (RAG retrieval): specific opinions, past decisions, project history — retrieved by semantic similarity
3. **Historical facts** (extraction-only): raw GitHub activity, comments, reviews — processed during synthesis, not injected at chat time

**Why it matters:** The current system prompt injects the full memory document (tier 1 + tier 2 mixed). As minis grow richer, this hits context limits and degrades quality. The three-tier hierarchy is the architecture for solving context-window pressure while maintaining quality: tier 1 stays small and permanent, tier 2 is retrieved on demand.

**Priority: P1** — This is the architecture for the chat retrieval system. File ticket.

---

### Idea 10: Emergent Role Discovery
**Source:** `my-minis/packages/minis/agents/README_SYNTHESIS.md`

Instead of assigning predefined labels ("Backend Developer", "Senior Engineer"), the synthesis agent discovers emergent roles from behavioral patterns: "Quality Guardian" (blocks PRs without tests, mentors on best practices), "Velocity Optimizer" (fast approvals for small PRs, parallel reviews), "Architecture Steward" (deep design discussions, long-term thinking). Each role has behavioral evidence, focus areas, and a 2-3 paragraph description.

**Why it matters:** Emergent roles make the mini self-describing. "This is the person who will always ask about test coverage before looking at anything else" is more useful than "Senior Engineer." These roles become the anchor for the soul document's identity section and surface as visible metadata to users.

**Priority: P2** — Enhance chief synthesizer with emergent role discovery.

---

## Failed Attempts and Lessons

### minis-v2: Fine-Tuning Was Abandoned
**What was tried:** Full ORPO + DoRA training pipeline on Qwen2.5-1.5B, RunPod deployment, vLLM multi-LoRA serving.
**Why it failed:** Training data quality bottleneck — the spirit-simulator-generated pairs were not sufficiently distinct from the base model. The `QualityJudge` frequently rejected pairs as not style-matched. Also: long iteration cycles (train → deploy → test → retrain) made it hard to improve quickly.
**Lesson:** Fine-tuning is only viable when you have high-quality, verified human-vs-AI preference pairs. The current prompt-based approach iterates faster and doesn't require GPU infrastructure. Fine-tuning is P3/enterprise.

### minis-v2: DuckDB + Parquet Was Overkill for the Pipeline
**What was tried:** Local DuckDB database with parquet silver layer, complex schema with 15+ tables.
**Why it failed:** Too much infrastructure for the extraction task. The pipeline became about managing the database rather than extracting personality.
**Lesson:** PostgreSQL + simple evidence table (current approach) is correct. Keep the data layer boring.

### my-minis: LangGraph Parallelism Was Complex to Debug
**What was tried:** Full LangGraph DAG with 6 parallel analysis agents (code, communication, technical, AI detection, behavioral context, personality typology) feeding a synthesis node.
**Why it failed:** LangGraph's graph concepts added significant overhead. Debugging parallel agent failures was hard. The final Personality schema became very complex.
**Lesson:** PydanticAI's simpler agent loop with parallel execution via asyncio is sufficient. The agent team approach (current) is right. The valuable output is the **agent design patterns** (personality typologist, behavioral context, AI detection), not the LangGraph orchestration.

### my-minis: Qdrant / Vector DB Complexity
**What was tried:** 5-collection Qdrant schema per user, with separate embeddings for PR approvals, rejections, comments, values, code.
**Why it failed:** Setup complexity, cost, and the insight that most retrieval can be done with pgvector on existing evidence rows.
**Lesson:** pgvector + existing evidence table is correct. Don't add a second vector database.

### Current Hackathon: Agent Harness Was Too Brittle (Session ff4c3ddc)
**What was tried:** Hand-rolled ReAct loop with forced tool use, turn limits, nudging heuristics, retry logic — all trying to force thorough evidence coverage.
**Why it failed:** Every constraint added to force thoroughness created a new failure mode. The harness was fighting the model rather than enabling it.
**Lesson:** The voice-mode brainstorm that produced the current autonomous-agent architecture was correct: "Give it tools. Don't program in compaction. Let it just go." The current pipeline embodies this.

---

## Original Brainstorm Section

The genesis of the current autonomous-agent architecture was captured in Claude session `ff4c3ddc-bb59-4e45-a233-a893119d8e9f`, lines 157-163, April 14, 2026.

### User Voice-Mode Transcript (line 160, lightly cleaned):
> "We shouldn't try to make the agent harness. I want something that's more like Claude Code versus the Claude API. I want it to be able to survive compaction without us having to program in what compaction looks like. I just want it to have all of these tools. We give it tools, we give it read-to-database, write-the-database, the evidence, all of that, as a tool, and that's it. And it just goes. I don't want to program in all of that stuff, I don't want to program in compaction. I want it to just work.
>
> It's not even a full 'swarm', and there needs to be orchestration steps in that there should maybe be a DAG of execution — these 5 agents go first, whatever — but I mean that can just be a prompt. Or two Claude function calls. The core issue is that we're building a super fragile harness and trying to manipulate it to literally 'force it to get full evidence' when we just need to have the full evidence as files in a file tree and let essentially Claude go ham on it and use the todos till it's thoroughly ingested every single bit, and we leverage agents so they deep-focus on different aspects of the sources we collected."

### Assistant Response Synthesis (line 163):
> "The core insight: Stop building a brittle harness. The current `agent.py` is a hand-rolled ReAct loop with forced tool use, turn limits, nudging, retry hacks — all trying to compensate for not trusting the agent. Instead:
> 1. **Evidence as files** — ingestion dumps raw data into a file tree
> 2. **Agent gets tools** — read files, search, write findings to DB, track progress
> 3. **Agent just goes** — no turn limits, no forced behavior, it stops when it's done
> 4. **Orchestration is just prompts** — not a DAG framework
> 5. **Compaction happens naturally** — findings are written to DB/files as the agent works, so context can be reclaimed without losing progress"

This exchange is the direct origin of the 3-stage pipeline (FETCH → EXPLORE → SYNTHESIZE) with DB-backed tool suite and autonomous agents that now defines the current architecture.

---

## Recommended VISION.md Edits

The following sections of `docs/VISION.md` would benefit from additions from the archaeology:

### Section: "The Ingredients" (currently items 1-5)
**Proposed addition after item 2 (explicit values):**
> **Their personality coordinates:** MBTI type, Big Five (OCEAN) scores, Enneagram wing — not because these frameworks are perfect, but because they give the soul document a validated scaffold and make the mini's psychology *legible* and *comparable* across minis. A team lead can see "INTJ, high Conscientiousness, low Agreeableness" and instantly calibrate expectations.

### Section: "The Technical Moat"
**Proposed addition:**
> **AI contamination filtering (ALLIE-new):** As developers adopt AI coding tools, their GitHub output increasingly contains AI-generated prose. A mini trained on "I'd be happy to help with that" from an AI-assisted PR description learns the wrong voice. Pre-processing evidence to separate human-authored from AI-assisted content is a prerequisite for high-fidelity soul documents at enterprise scale.

### Section: "What This Document Is NOT"
No changes needed.

---

## Credentials / Security Flags

**IMPORTANT:** The following files in previous repos contain what appear to be API keys. Treat as potentially live or previously live credentials:

- `/home/Allie/develop/minis-v2/.env` — Contains `GOOGLE_API_KEY`, `GEMINI_API_KEY`, `LANGSMITH_API_KEY`, `RUNPOD_API_KEY`. Values visible in plaintext. **Verify these have been rotated.**
- `/home/Allie/develop/my-minis/.env` — Contains `GOOGLE_API_KEY`. **Verify rotated.**
- The `RUNPOD_API_KEY` value was also present in a session transcript (agent task prompt in `f69d7f58`), suggesting it was active at time of that session.

These repos should not be pushed to any public remote in their current state.

---

## Memory Files Added

See new memory file: `~/.claude/projects/-home-Allie-develop-minis-hackathon/memory/archaeology_findings.md`

---

*This document is read-only archaeology. Do not modify previous repos. Do not execute code from previous repos.*
