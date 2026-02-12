# Minis "Brain" Architecture Upgrade Proposal

## 1. Critique of Current Architecture

The current memory system (`memory_assembler.py` and `spirit.py`) is essentially a **flat, static document assembler**.

*   **Structure:** It aggregates facts into a single Markdown file (`memory_content`) divided by high-level categories (Projects, Expertise, Values).
*   **Storage:** Stored as a `Text` blob in the database.
*   **Retrieval:** The *entire* document is injected into the system prompt context window.
*   **Limitations:**
    *   **Scalability:** As a developer's history grows (more repos, more stacks), the context window fills up with irrelevant noise.
    *   **Specificity:** It excels at high-level "vibes" (traits, values) but fails at low-level "facts" (e.g., "How did I configure Webpack in Project X?").
    *   **Static:** It doesn't adapt to the conversation. If I ask about "Rust", it still loads my "React" opinions into the context.
    *   **No Relationships:** It knows I use "React" and I worked on "Project A", but it doesn't structurally link them unless the LLM happens to generate a sentence combining them.

## 2. The New "Brain" Architecture

To make the system "shockingly robust," we need to move from a **Document Model** to a **Knowledge Graph + Retrieval Model**.

### A. Data Structure: The Developer Knowledge Graph

Instead of flat Markdown, we model the developer's mind as a graph of entities and relationships.

**Core Entities (Nodes):**
1.  **`Technology`**: Languages, frameworks, libraries, tools (e.g., "React", "Docker", "vim").
    *   *Properties:* `name`, `category`, `proficiency_score`.
2.  **`Project`**: Repositories or major bodies of work.
    *   *Properties:* `name`, `description`, `role`, `dates`.
3.  **`Pattern`**: Specific coding idioms or architectural choices.
    *   *Properties:* `name` (e.g., "Early Returns"), `description`, `code_snippet`.
4.  **`Opinion`**: Subjective stances.
    *   *Properties:* `topic`, `sentiment` (positive/negative), `content`, `intensity`.
5.  **`Experience`**: Specific events or achievements.
    *   *Properties:* `summary`, `context`.

**Relationships (Edges):**
*   `(Project) --[USES]--> (Technology)`: "Project Alpha uses Next.js 14"
*   `(Developer) --[EXPERT_IN]--> (Technology)`: "Expert in Python"
*   `(Developer) --[PREFERS]--> (Pattern)`: "Prefers functional programming"
*   `(Developer) --[DISLIKES]--> (Technology)`: "Hates Jenkins"
*   `(Opinion) --[ABOUT]--> (Technology/Pattern)`: "Thinks Redux is boilerplate-heavy"

### B. Storage Strategy

We need a hybrid storage approach:

1.  **Vector Store (Semantic Memory):**
    *   *What:* Embeddings of `Opinion`, `Pattern`, and `Experience` nodes.
    *   *Why:* To answer fuzzy questions like "What do you think about state management?" or "Have you ever dealt with complex migrations?"
    *   *Implementation:* `pgvector` (since you're likely using Postgres) or a dedicated vector DB (Chroma/Pinecone).

2.  **Relational/Graph Store (Structural Memory):**
    *   *What:* The explicit links between Projects and Technologies.
    *   *Why:* To answer factual questions like "Which projects use Tailwind?" or "List your Rust repos."
    *   *Implementation:* Normalize into SQL tables (`projects`, `technologies`, `project_technologies`) OR use a JSONB column with a graph schema if flexibility is key.

### C. Extraction Strategy (The "Explorer" Upgrade)

The `Explorer` agents need to be more specialized.

1.  **`TechStackExplorer` (Deterministic):**
    *   *Input:* `package.json`, `Cargo.toml`, `requirements.txt`, `Dockerfile`.
    *   *Action:* deterministic parsing.
    *   *Output:* `(Project) -> USES -> (Technology)` edges with version numbers.

2.  **`PatternExplorer` (Heuristic/LLM):**
    *   *Input:* Source code files (sampled).
    *   *Action:* LLM analysis of code style. "Does this code use classes or functions? Async/await or promises? heavy commenting or self-documenting?"
    *   *Output:* `(Developer) -> PREFERS -> (Pattern)` edges.

3.  **`OpinionMiner` (Semantic):**
    *   *Input:* PR comments, Commit messages, READMEs, Issue discussions.
    *   *Action:* LLM extraction of subjective statements.
    *   *Output:* `Opinion` nodes linked to `Technology` or `Pattern`.

### D. Injection & Retrieval Strategy (The "Recall" Loop)

Instead of dumping everything into the system prompt, we implement a **RAG (Retrieval-Augmented Generation)** loop during the chat.

**The "Recall" Workflow:**

1.  **User Query:** "How should I structure a new Next.js app?"
2.  **Intent Classification:** The system identifies the query is about *Next.js* (Entity) and *Structure* (Pattern).
3.  **Retrieval:**
    *   *Vector Search:* Find `Opinion` and `Pattern` nodes semantically related to "Next.js structure", "architecture", "folders".
    *   *Graph Traversal:* Find `Project` nodes that use `Next.js`.
4.  **Context Assembly:** Construct a dynamic "Active Memory" section.
    *   "I have opinions on Next.js folder structure (found 3)."
    *   "I used Next.js in Project A and Project B."
    *   "I prefer the 'App Router' pattern."
5.  **Generation:** The LLM generates the response using this retrieved context, maintaining the Persona/Voice.

## 3. Heuristic Prompts for "Deep Technical Knowledge"

Here are specific prompts to extract "implicit knowledge" that goes beyond keywords.

### A. The "Code Taste" Analyst (Pattern Extraction)

```text
You are an expert code stylistic analyst.
Analyze these 5 source files from the developer's repository: {file_list}

Identify their **Implicit Coding Preferences**. Do NOT describe what the code does. Describe HOW it is written.
Focus on:
1. **Error Handling:** Do they use `try/catch` everywhere, or `Result` types? Do they let errors bubble up or handle them locally?
2. **Abstraction Level:** Do they prefer "magic" abstractions (decorators, metaprogramming) or explicit, verbose code?
3. **State Management:** (If UI) Context, Redux, Signals, or prop drilling?
4. **Typing:** Strict typing (no `any`), loose typing, or dynamic?
5. **Comments:** Why-comments, What-comments, or no comments?

Output a JSON list of "Patterns":
[
  {
    "name": "Defensive Coding",
    "description": "Heavily validates inputs at function boundaries.",
    "evidence_snippet": "..."
  },
  {
    "name": "Functional Style",
    "description": "Prefers `.map`/`.reduce` chains over loops; avoids mutation.",
    "evidence_snippet": "..."
  }
]
```

### B. The "War Story" Miner (Experience Extraction)

```text
Analyze these Commit Messages and PR Descriptions.
Look for **"War Stories"** - evidence of difficult debugging, performance optimization, or major refactors.

Ignore: "fix typo", "update deps", "feature add".
Target: "tracked down memory leak", "refactored auth flow", "migrated database", "fixed race condition".

For each finding, extract an "Experience" entry:
{
  "topic": "Memory Leak debugging",
  "context": "Project: {repo_name}",
  "summary": "Spent 3 days tracking down a cyclic reference in the WebSocket handler.",
  "complexity_score": 9/10,
  "evidence_quote": "finally caught the leak in the socket closure..."
}
```

### C. The "Opinionated Engineer" (Opinion Extraction)

```text
Analyze these Pull Request Reviews and Issue Comments.
Extract **Strong Opinions** and **Biases**.

Look for:
- "I don't like X because..."
- "We should always use Y..."
- "Z is an anti-pattern."
- "This is cleaner."

Output "Opinion" entries:
{
  "subject": "Tailwind CSS",
  "sentiment": "negative",
  "claim": "Believes Tailwind clutters HTML and makes debugging hard.",
  "quote": "this class string is unreadable, let's move to modules",
  "intensity": "high"
}
```
