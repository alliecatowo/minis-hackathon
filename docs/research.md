# Minis Hackathon Research Document

> **Date:** February 9, 2026
> **Deadline:** February 20, 2026
> **Scope:** Deep research on personality cloning, AI tooling, frontend UX, GitHub integration, and Claude Code extensibility

---

## Table of Contents

1. [Deep Personality Cloning with LLMs](#1-deep-personality-cloning-with-llms)
2. [AI Frameworks & Tools (2025-2026)](#2-ai-frameworks--tools-2025-2026)
3. [Frontend & Chat UX](#3-frontend--chat-ux)
4. [GitHub Integration](#4-github-integration)
5. [Claude Code Integration](#5-claude-code-integration)
6. [Hackathon Priorities & Recommendations](#6-hackathon-priorities--recommendations)

---

## 1. Deep Personality Cloning with LLMs

### 1.1 State of the Art

The field of LLM-based personality simulation has matured significantly. Key benchmarks now exist:

- **TwinVoice Benchmark** (2025): Evaluates persona simulation across three dimensions -- Social Persona, Interpersonal Persona, and Narrative Persona -- decomposed into six capabilities: opinion consistency, memory recall, logical reasoning, lexical fidelity, persona tone, and syntactic style. ([paper](https://arxiv.org/abs/2510.25536))

- **BehaviorChain Benchmark** (2025): First benchmark for continuous human behavior simulation, with 15,846 distinct behaviors across 1,001 personas. Current state-of-the-art models still struggle with continuous behavioral consistency. ([paper](https://arxiv.org/abs/2502.14642))

- **Stanford Generative Agents** (2024): 1,052 real individuals modeled via 2-hour qualitative interviews. Agents replicate participant responses on the General Social Survey **85% as accurately as participants replicate their own answers two weeks later**. This is the gold standard result. ([paper](https://arxiv.org/abs/2411.10109), [Stanford HAI](https://hai.stanford.edu/policy/simulating-human-behavior-with-ai-agents))

**Key takeaway for Minis:** The Stanford result proves that **rich, unstructured personal context** (interview transcripts) fed directly into the prompt produces the most convincing personas. The simplest approach -- augmenting the LLM prompt with rich data -- consistently outperforms more complex methods.

### 1.2 Prompt Engineering vs Fine-Tuning vs RAG for Personality

| Approach | Best For | Limitations | Hackathon Feasibility |
|----------|----------|-------------|----------------------|
| **Prompt Engineering** | Fast iteration, personality embodiment | Can feel generic/"ChatGPT-like" if not carefully crafted | **HIGH** -- our current approach |
| **Fine-Tuning (LoRA)** | Memorizing tone, style, pet phrases | Requires curated training data; doesn't teach new facts | LOW -- too slow for hackathon |
| **RAG** | Grounding in factual/historical context | Retrieval quality varies; adds latency | MEDIUM -- useful for memory |
| **Hybrid (Prompt + RAG)** | Best of both worlds | Most complex to build | **RECOMMENDED** -- phased approach |

**Recommendation:** Start with rich prompt engineering (our current approach), then layer RAG for contextual memory retrieval. Fine-tuning is a post-hackathon goal.

The research paper ["RAGs to Riches"](https://arxiv.org/abs/2509.12168) proposes using RAG-like few-shot learning for role-playing, where reference demonstrations are retrieved and injected based on conversational context. Models using this approach incorporate 35% more authentic tokens and are consistently judged as more in-character across 453 interactions.

### 1.3 What Makes Personality Clones Convincing vs Uncanny

Research identifies clear patterns:

**What makes clones feel CONVINCING:**
- **Consistency** across topics and time -- the persona doesn't shift randomly
- **Appropriate imperfection** -- real people have quirks, hesitations, opinions they're unsure about
- **Decision framework alignment** -- reasoning *like* the person, not just talking like them
- **Conflict behavior** -- how the persona handles disagreement reveals true character (our core insight is validated by research: "conflict encourages individuals to search for attributions")
- **Emotional range** -- not always agreeable; real people push back, get frustrated, show enthusiasm unevenly

**What causes UNCANNY VALLEY:**
- **Inconsistency** -- starting professional then suddenly casual (humans don't do this)
- **"Always Happy" syndrome** -- responding cheerfully to hostile input breaks immersion
- **Lack of cognitive grounding** -- linguistic competence without authentic reasoning creates "a liminal space between machine and human that generates mistrust"
- **Over-articulation** -- real people don't perfectly articulate every thought
- **Missing lived experience** -- referencing events the person never actually experienced

**Key insight from [PersonaLLM research](https://www.emergentmind.com/topics/personallm):** While LLMs can align with assigned Big Five traits via prompt conditioning, biases in human detection persist. The gap is in **specificity** -- generic personality traits feel hollow; specific decision patterns feel real.

### 1.4 Decision Framework Cloning -- The Core Innovation

This is Minis' biggest opportunity. Most personality systems clone *tone* (how someone sounds). The breakthrough is cloning *reasoning* (how someone thinks).

**Techniques for decision framework extraction:**

1. **Conflict Evidence Mining** (our approach): When a developer disagrees with a PR, pushes back on an issue, or chooses an unconventional solution, they reveal their actual values. This is backed by psychology research showing that conflict situations force attribution-seeking behavior, exposing true decision heuristics.

2. **Cognitive Decision Routing**: Inspired by Kahneman's dual-process theory (System 1/System 2), the [CDR framework](https://arxiv.org/html/2508.16636) dynamically determines reasoning strategies based on query characteristics. Minis could label which decisions a developer makes "fast" (intuitive) vs "slow" (deliberative).

3. **Sideloading Technique** ([LessWrong](https://www.lesswrong.com/posts/7pCaHHSeEo8kejHPk/sideloading-creating-a-model-of-a-person-via-llm-with-very)): Organize personality data into three tiers:
   - **Core facts** (always in system prompt): values, communication style, decision patterns, technical philosophy
   - **Long-term memory** (RAG retrieval): specific opinions, past decisions, project history
   - **Historical facts** (processed for extraction only): raw GitHub activity, comments, reviews

4. **Anthropic Persona Vectors** ([research](https://www.anthropic.com/research/persona-vectors)): Personality traits exist as decomposable, manipulable directions in model activation space. While we can't directly use this (requires model internals), it validates that **personality is compositional** -- you can build a convincing persona from independent trait vectors rather than needing a holistic approach.

### 1.5 System Prompt Engineering Best Practices

Based on 2025-2026 research and practice:

**Structure the system prompt as an "onboarding document":**
```
1. Identity statement (who this person IS, not who they're pretending to be)
2. Core values & decision principles (extracted from conflict evidence)
3. Technical philosophy (language preferences, architecture opinions, code style)
4. Communication patterns (how they argue, how they praise, how they explain)
5. Behavioral boundaries (what they would NEVER say/do)
6. Specific examples (few-shot demonstrations of characteristic responses)
```

**Critical techniques:**
- Use **"You are X"** not "Imagine you are X" -- direct role assignment outperforms imaginative framing
- Define **expertise level and context** clearly
- Include **negative constraints** -- what the person would NOT do is as defining as what they would
- Add **few-shot examples** of actual responses (from GitHub comments, PR reviews) as reference demonstrations
- Keep the system prompt under 5,000 tokens for optimal performance; use RAG for overflow

### 1.6 Memory Architecture for Personality

The [Stanford Generative Agents architecture](https://arxiv.org/abs/2304.03442) provides the gold standard:

1. **Memory Stream**: Complete record of experiences in natural language
2. **Reflection**: Periodic synthesis of memories into higher-level observations
3. **Planning**: Using reflections to inform future behavior

For Minis, this maps to:
- **Memory Stream**: Raw GitHub activity (commits, reviews, issues, comments)
- **Reflection**: Our "spirit synthesis" step -- LLM-extracted values, patterns, decision frameworks
- **Planning**: The system prompt that guides the engram's behavior

**Mem0 library** ([paper](https://arxiv.org/pdf/2504.19413)): Production-ready memory layer for AI agents with scalable long-term memory. Worth evaluating for storing and retrieving persona-specific context.

### 1.7 The PersonaChat Lineage

The [PersonaChat dataset](https://arxiv.org/pdf/1801.07243) (Zhang et al., 2018) established the field with 10.9K dialogues and 5 persona-descriptive sentences per speaker. Key evolution:

- **PersonaChat** (2018): Basic persona consistency via profile sentences
- **BlendedSkillTalk** (2020): Added knowledge grounding + empathy to persona
- **PersonalityChat** (2024): Conversation distillation for personalized dialog with facts AND traits
- **TwinVoice** (2025): Multi-dimensional benchmark covering social, interpersonal, and narrative persona

**Lesson for Minis:** The field has moved from simple "5 sentences describing a person" to rich, multi-dimensional persona modeling. Our approach of mining GitHub for behavioral evidence is more aligned with the latest research than earlier profile-based methods.

---

## 2. AI Frameworks & Tools (2025-2026)

### 2.1 LLM Abstraction Layers

| Framework | Best For | Bundle Size | Streaming | Provider Count | Hackathon Pick? |
|-----------|----------|-------------|-----------|----------------|-----------------|
| **Vercel AI SDK** | Next.js/React apps, streaming UX | 34.3 kB (via OpenAI) | First-class | 25+ | **YES** (frontend) |
| **LiteLLM** | Multi-provider backend, unified API | N/A (Python) | Yes | 100+ | **YES** (backend) |
| **LangChain** | Complex RAG/agent pipelines | 101.2 kB | Yes | Many | Maybe later |

**Recommendation for Minis:**
- **Backend:** Continue with LiteLLM for provider flexibility. Monitor for [known production issues](https://github.com/BerriAI/litellm) (memory leaks, latency at scale). For hackathon scale, these won't matter.
- **Frontend:** Vercel AI SDK is the clear winner for streaming chat UX in React/Next.js. Reduces boilerplate from 100+ lines to ~20. Use `useChat` hook for primary chat interface.
- **Skip LangChain** unless we need complex RAG pipelines. It adds unnecessary complexity for our use case.

### 2.2 Agent Frameworks

| Framework | Language | Best For | Complexity |
|-----------|----------|----------|------------|
| **LangGraph** | Python/JS | Fine-grained control, lowest latency | High |
| **Mastra** | TypeScript | Opinionated full-stack, auto OpenAPI docs | Medium |
| **CrewAI** | Python | Multi-agent role-based orchestration | Low |
| **Pydantic AI** | Python | Type-safe agents, quick prototypes | Low |

**Recommendation:** We don't need an agent framework for the hackathon. Our pipeline (ingest -> extract -> synthesize -> chat) is a straightforward pipeline, not an autonomous agent. If we need agent-like behavior later (e.g., autonomous PR review), evaluate **Mastra** (TypeScript alignment) or **LangGraph** (performance).

Sources: [Langfuse comparison](https://langfuse.com/blog/2025-03-19-ai-agent-comparison), [2026 tier list](https://medium.com/data-science-collective/the-best-ai-agent-frameworks-for-2026-tier-list-b3a4362fac0d)

### 2.3 Structured Output from LLMs

**Best practices (2025-2026):**

1. **API-native structured outputs** are now available from both OpenAI and Anthropic. Claude supports structured outputs via `anthropic-beta: structured-outputs-2025-11-13` header with JSON schema enforcement at the token generation level. ([Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs))

2. **Tool use / function calling** is better than JSON mode for extraction tasks. Define tools with `strict: true` for guaranteed schema compliance.

3. **Pydantic/Zod schemas** are the standard for defining output structure. Both Claude and OpenAI support them natively.

4. **For Minis specifically:** Use structured outputs for the value extraction step (GitHub data -> structured personality traits) and tool use for the chat interface (allowing the engram to "use tools" like searching its own memories).

### 2.4 MCP (Model Context Protocol)

MCP has become the standard for connecting LLMs to external systems. Key developments:

- **Spec version 2025-11-25**: Latest stable specification
- **Streamable HTTP** replaced deprecated SSE transport (2025-06-18)
- **OAuth 2.1** security: MCP servers are now officially OAuth Resource Servers
- **100M+ monthly downloads**, 3,000+ servers indexed on MCP.so
- **Microsoft adoption**: MCP as foundational layer for agentic computing in Windows 11

**Best practices for building our MCP server:**
1. Single responsibility: one server per clear purpose
2. Make tool calls idempotent with client-generated request IDs
3. Support stdio for maximum client compatibility + Streamable HTTP for networked use
4. Use pagination tokens for list operations
5. Externalize configuration via environment variables
6. Implement health checks and structured logging
7. Include thorough tool descriptions with enums and failure modes

Sources: [MCP Best Practices](https://modelcontextprotocol.info/docs/best-practices/), [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)

---

## 3. Frontend & Chat UX

### 3.1 AI Chat Interface Best Practices (2026)

**Core principles:**
- Users decide within **5 seconds** whether a chatbot is worth engaging
- **67% of users** leave and never return after getting stuck in a loop
- Short, direct responses that mimic natural conversation keep users engaged
- Typing indicators, guided micro-interactions, and visual journeys make chats feel human

**Emerging trends:**
- AI copilots replacing static flows
- Emotion-aware UI driven by sentiment detection
- Hybrid interfaces combining voice, visuals, and text
- Transparent AI showing why decisions were made
- Flow resilience: bots that bounce back after errors

**For Minis specifically:**
- The chat interface should **embody** the personality -- not just in text but in UI choices
- Show the persona's "confidence" or "certainty" on different topics
- Display personality traits visually (radar chart, tag cloud)
- Allow users to see *why* the engram responded a certain way (transparency)

Sources: [Chatbot UX 2026](https://www.letsgroto.com/blog/ux-best-practices-for-ai-chatbots), [Netguru UX tips](https://www.netguru.com/blog/chatbot-ux-tips)

### 3.2 Open Source Chat UI Components

**Top recommendation: [assistant-ui](https://www.assistant-ui.com/)**
- TypeScript/React library, Y Combinator W25
- 50k+ monthly downloads, most popular AI chat UI library
- Production-ready: streaming, auto-scroll, retries, attachments, markdown, code highlighting
- Integrates with Vercel AI SDK and LangGraph
- Latest version: 0.12.9 (February 2026)

**Alternatives:**
- **chatscope/chat-ui-kit-react**: Lower-level building blocks
- **nlux**: Zero dependencies, good for lightweight embeds
- **LlamaIndex Chat UI**: LLM-focused components

**Recommendation for hackathon:** Use **assistant-ui** with **Vercel AI SDK**. This gives us a production-quality chat interface with minimal effort. Customize the UI to reflect personality (colors, avatar, tone indicators).

### 3.3 Streaming UX Patterns

With Vercel AI SDK v6:
- Use `useChat` hook for streaming chat with automatic state management
- `Output.object()` API for structured generation in UI
- Typing effects should be in their own component for reusability
- Display model reasoning separately from main response
- Handle errors gracefully with retry mechanisms

Sources: [Vercel AI SDK docs](https://ai-sdk.dev/docs/introduction), [LogRocket tutorial](https://blog.logrocket.com/nextjs-vercel-ai-sdk-streaming/)

---

## 4. GitHub Integration

### 4.1 GitHub Apps vs GitHub Actions

| Feature | GitHub Apps | GitHub Actions |
|---------|-------------|----------------|
| **Trigger** | Webhooks (immediate) | Events (may queue) |
| **Hosting** | Self-hosted server | GitHub-hosted runners |
| **State** | Can maintain state, build UI | Ephemeral per run |
| **Cost** | Your infrastructure | Free for public repos |
| **Latency** | Immediate webhook handling | May have queue delays |
| **Best for** | PR review bots, interactive apps | CI/CD, long-running tasks |

**Recommendation for Minis PR Review:** Use a **GitHub App** (not Actions) because:
1. PR review needs to be fast and responsive (immediate webhook handling)
2. We need to maintain persona state between interactions
3. We want to offer an installable app experience
4. The app can build a UI for configuration

### 4.2 How AI Code Review Tools Work

**CodeRabbit architecture** (market leader, 2M+ repos):
1. GitHub App receives PR webhook
2. Diff is analyzed with code graph analysis
3. LLM generates line-by-line comments + PR summary
4. Comments posted via GitHub API
5. Supports MCP integration for connecting to Jira, Linear, docs
6. Runs in ephemeral containers with zero data retention post-review

**Key features to emulate:**
- Line-by-line comments (not just PR-level summary)
- Release note generation
- Interactive chat within PR comments
- Learnable rules from user feedback

**For Minis differentiation:** Our PR reviews are personality-driven. The engram doesn't just review code -- it reviews code *as that specific developer would*. This means:
- Commenting on patterns the developer cares about (based on their GitHub history)
- Using the developer's communication style in review comments
- Prioritizing the same things the developer prioritizes

Sources: [CodeRabbit docs](https://docs.coderabbit.ai/platforms/github-com), [AI code review comparison](https://www.codeant.ai/blogs/best-github-ai-code-review-tools-2025)

### 4.3 Probot Framework

**Status:** Still actively maintained (last update Feb 3, 2026). Probot remains the standard framework for building GitHub Apps in Node.js.

**Strengths:**
- Handles OAuth, webhook verification, authentication boilerplate
- EventEmitter-like API for webhook handling
- Express server underneath (can build UI, store data)
- Active ecosystem

**Alternative:** Build directly on Octokit + Express, but Probot saves significant boilerplate.

**Recommendation:** Use **Probot** for the GitHub App. It's battle-tested and handles the hard parts (auth, webhooks) so we can focus on the personality-driven review logic.

---

## 5. Claude Code Integration

### 5.1 Claude Code Skills

Skills are Claude Code's mechanism for **portable, reusable expertise**. Key characteristics:

- **Progressive disclosure**: Metadata loads first (~100 tokens), full instructions when needed (<5k tokens), bundled files only as required
- **Invocable via slash commands**: e.g., `/deploy`, `/review`
- **Auto-discoverable**: Claude loads relevant skills automatically based on task context
- **Cross-platform**: Work in Claude Code, Claude.ai, and via API

**For Minis, a skill could:**
- `/summon <github-username>` -- Create or load an engram for chat
- `/review-as <username>` -- Review current code as that developer's personality
- `/pair-with <username>` -- Pair program with a personality clone
- `/ask <username> <question>` -- Quick question to an engram about architectural decisions

### 5.2 Claude Code Agent Teams

Agent Teams (experimental, released Feb 5, 2026) are **coordinated groups of independent Claude Code instances**:

- **Team Lead** creates and coordinates teammates
- **Teammates** have their own context windows and work in parallel
- **Shared task list** with dependency tracking
- **Direct messaging** between agents (peer-to-peer, not just lead-spoke)

**Enable with:**
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

**For Minis integration:** Agent Teams could enable "pair programming with engrams" where:
- One agent is the developer's engram (personality clone)
- Another agent is the actual coding assistant
- They debate architectural decisions, with the engram providing the human developer's perspective

### 5.3 MCP Server Integration with Claude Code

Claude Code natively supports MCP servers. Our Minis MCP server would allow Claude Code users to:
- Query personality profiles: `get_engram(username)`
- Chat with engrams: `chat_with_engram(username, message)`
- Get personality-driven code review: `review_code(username, diff)`
- Search personality traits: `search_values(username, topic)`

**Best approach:**
1. Build MCP server with stdio transport (maximum compatibility)
2. Add Streamable HTTP for networked access
3. Register tools with clear descriptions and typed schemas
4. Users install via Claude Code MCP settings

### 5.4 What Makes a Great Claude Code Extension

Based on the ecosystem analysis:

1. **Solve a real workflow problem** -- don't just wrap an API
2. **Progressive complexity** -- simple by default, powerful when needed
3. **Combine MCP (connectivity) + Skills (expertise)** -- MCP alone is just plumbing
4. **Fast response times** -- Claude Code users expect interactive speed
5. **Clear tool descriptions** -- Claude's effectiveness depends entirely on understanding what tools do

Sources: [Skills explained](https://claude.com/blog/skills-explained), [Claude Code Agent Teams](https://addyosmani.com/blog/claude-code-agent-teams/)

---

## 6. Hackathon Priorities & Recommendations

### 6.1 What to Build (Priority Order)

Given the Feb 20 deadline:

**P0 -- Must Have:**
1. **Improve personality synthesis quality** using the techniques from Section 1 (conflict evidence mining, decision framework extraction, structured system prompts, few-shot examples from actual GitHub comments)
2. **MCP Server** for Minis -- allows Claude Code and other MCP clients to interact with engrams
3. **Plugin architecture** for ingestion sources (so we can add Claude Code conversations, Twitter, etc.)

**P1 -- Should Have:**
4. **GitHub App for PR review** -- personality-driven code review is the killer demo
5. **Claude Code skill** -- `/summon` and `/review-as` commands
6. **Frontend improvements** -- personality visualization, better chat UX

**P2 -- Nice to Have:**
7. **RAG-based memory** for richer context retrieval during chat
8. **Agent Teams integration** -- pair programming with engrams
9. **Additional ingestion sources** (Twitter, blog posts, conference talks)

### 6.2 Top 5 Recommendations

1. **Invest most time in personality quality, not infrastructure.** The Stanford research proves that rich, detailed personal context in the prompt beats sophisticated architectures. Focus the value extraction pipeline on mining *decision patterns* and *conflict evidence* from GitHub, not just tone and topics.

2. **Build the MCP server as the universal integration point.** MCP is the standard protocol for connecting LLMs to external systems. One well-built MCP server unlocks Claude Code, VS Code Copilot, and every other MCP-compatible client simultaneously. Use stdio + Streamable HTTP transports.

3. **GitHub App for PR review is the killer demo.** "What would senior-dev-X say about this PR?" is immediately compelling and demonstrable. Use Probot for the framework. Differentiate from CodeRabbit by making reviews personality-driven, not just technically accurate.

4. **Use assistant-ui + Vercel AI SDK for the frontend.** Don't build chat UI from scratch. assistant-ui gives production-quality streaming chat with minimal effort. Spend UI time on personality visualization and differentiation instead.

5. **Structure system prompts as "onboarding documents" with few-shot examples.** The biggest quality improvement will come from restructuring the system prompt to include: identity statement, core values, decision principles (from conflict evidence), communication patterns, behavioral boundaries, and actual examples of the person's real responses extracted from GitHub comments/reviews.

### 6.3 Architecture Decisions

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| LLM abstraction | LiteLLM (backend) + Vercel AI SDK (frontend) | Best-in-class for each layer |
| Chat UI | assistant-ui | Production-ready, streaming-first |
| GitHub integration | GitHub App via Probot | Immediate webhooks, stateful, installable |
| MCP transport | stdio + Streamable HTTP | Maximum compatibility |
| Personality approach | Rich prompt + RAG (later) | Proven by Stanford research; fine-tuning is post-hackathon |
| Structured output | Claude structured outputs + tool use | Native schema enforcement, `strict: true` |
| Agent framework | None for now | Our pipeline isn't an autonomous agent |

### 6.4 Key Papers & Resources

| Resource | Why It Matters |
|----------|---------------|
| [Generative Agents (Stanford, 2024)](https://arxiv.org/abs/2411.10109) | 85% accuracy from 2-hour interviews -- validates rich-context approach |
| [Persona Vectors (Anthropic)](https://www.anthropic.com/research/persona-vectors) | Personality is compositional and manipulable |
| [RAGs to Riches](https://arxiv.org/abs/2509.12168) | RAG-based few-shot learning for persona consistency |
| [Sideloading (LessWrong)](https://www.lesswrong.com/posts/7pCaHHSeEo8kejHPk/sideloading-creating-a-model-of-a-person-via-llm-with-very) | Three-tier fact hierarchy for personality prompts |
| [TwinVoice Benchmark](https://arxiv.org/abs/2510.25536) | Six dimensions of persona evaluation |
| [BehaviorChain](https://arxiv.org/abs/2502.14642) | Continuous behavior simulation challenges |
| [PersonaChat](https://arxiv.org/pdf/1801.07243) | Foundational persona-grounded dialogue dataset |
| [Claude Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) | Native JSON schema enforcement |
| [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25) | Latest MCP protocol spec |
| [assistant-ui](https://www.assistant-ui.com/) | Best React chat UI library |
| [Claude Code Skills](https://claude.com/blog/skills-explained) | How to build Claude Code extensions |
| [Agent Teams](https://addyosmani.com/blog/claude-code-agent-teams/) | Multi-agent coordination in Claude Code |

### 6.5 Trade-off Analysis

**Prompt Engineering vs Fine-Tuning:**
- Prompt engineering: Fast iteration, works now, provider-agnostic. Limited by context window.
- Fine-tuning: More authentic personality internalization. Requires training data curation, per-model work, slow iteration.
- **Decision: Prompt engineering for hackathon.** Fine-tuning is a post-launch optimization.

**GitHub App vs GitHub Action:**
- App: Immediate webhook response, stateful, installable marketplace presence. Requires hosting.
- Action: Zero hosting cost, simple setup. Queued execution, ephemeral state.
- **Decision: GitHub App.** PR review needs immediate response and personality state.

**Build vs Buy Chat UI:**
- Build: Full customization, no dependencies. Time-consuming, bugs.
- assistant-ui: Production-ready, streaming, accessible. Some customization constraints.
- **Decision: assistant-ui.** Customize the personality visualization layer, not the chat mechanics.

**Single MCP Server vs Multiple:**
- Single: Simpler deployment, one integration point. May grow unwieldy.
- Multiple: Clean separation of concerns. More complexity for users.
- **Decision: Single server** with well-organized tools. Split later if needed.
