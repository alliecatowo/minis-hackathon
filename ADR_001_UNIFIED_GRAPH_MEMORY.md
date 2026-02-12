# Architecture Decision Record: Unified Semantic-Episodic Graph Memory

## Status
Proposed

## Context
The current memory architecture in `minis` separates "Knowledge" (Brain) from "Personality" (Soul) implicitly by storing them as flat Markdown bullet points (`MemoryEntry`) mixed with unstructured text. The `memory_assembler.py` aggregates these into a single document, but ignores the structured `KnowledgeGraph` and `PrinciplesMatrix` data structures that are already defined in the codebase and available to the Explorer agents.

The user requires a definitive SOTA architecture for 2025/2026 that resolves the "half-baked" memory attempts and unifies "Brain" and "Soul".

## Research Synthesis (State of the Art 2026)
1.  **Unified Graph Architectures (GraphRAG):** Modern cognitive architectures (e.g., Microsoft's GraphRAG, MemGPT 2.0) have moved away from purely vector-based retrieval (RAG) because vectors struggle with global queries ("What are their core values?") and multi-hop reasoning ("How does their hatred of OOP influence their React code?"). The consensus is a **Knowledge Graph** where entities are linked by semantic relationships.
2.  **Hybrid Search:** Retrieval is performed via a "Hybrid Search" mechanism:
    *   **Graph Traversal:** For reasoning and finding connected concepts (e.g., `Value:Simplicity` -> `implies` -> `Opinion:Anti-ORM`).
    *   **Vector Similarity:** For fuzzy matching on unstructured text chunks (episodic memories) attached to graph nodes.
3.  **BDI (Belief-Desire-Intention) in LLMs:** "Soul" is modeled not as a separate "prompt injection" but as a subgraph of **Principles** that acts as a filter on the "Knowledge" graph.

## Decision: Unified Graph Memory
We will unify "Brain" and "Soul" into a single **Semantic-Episodic Graph**.

### The Schema
The "Memory" will no longer be just a Markdown file. It will be a serializable Graph structure containing:
*   **Nodes:**
    *   `Concept`: Technologies, Patterns (e.g., "React", "Clean Code").
    *   `Episode`: Specific events (e.g., "Review of PR #42", "Authored commit 8a3f").
    *   `Principle`: Behavioral axioms (e.g., "Reject Complexity").
*   **Edges:**
    *   `Semantic`: `USED_BY`, `CREATED_WITH`, `IS_A`.
    *   `Episodic`: `OCCURRED_AT`, `DEMONSTRATED_BY`.
    *   `Causal`: `MOTIVATES`, `CONFLICTS_WITH`.

### "Soul" Implementation
The "Soul" is simply a specific subgraph:
*   **Values** are `Principle` nodes.
*   **Traits** are `Attribute` nodes linked to the Identity node.
*   **Style** is captured in `Pattern` nodes linked to `Context` nodes.

## Consequences
1.  **Refactoring `memory_assembler.py`:** It must now merge `KnowledgeGraph` and `PrinciplesMatrix` objects from `ExplorerReport`s, not just `MemoryEntry` lists.
2.  **Persistence:** We need to save the graph to a format like JSON (or GraphML) alongside the human-readable Markdown.
3.  **Retrieval:** Future chat interactions will need a graph-aware retriever (out of scope for this specific ADR, but enabled by it).

## Refactoring Plan
1.  **Modify `memory_assembler.py`**:
    *   Import `KnowledgeGraph`, `KnowledgeNode`, `KnowledgeEdge`, `PrinciplesMatrix`.
    *   Implement `merge_graphs(graphs: List[KnowledgeGraph]) -> KnowledgeGraph`.
    *   Implement `merge_principles(matrices: List[PrinciplesMatrix]) -> PrinciplesMatrix`.
    *   Update `assemble_memory` to output a `UnifiedMemory` object (containing Graph, Principles, and Flat Entries) and serialize it.
    *   Update the Markdown generation to *read* from this Unified Graph to produce the `# Knowledge & Beliefs` document, ensuring the "Brain" and "Soul" data is visible to the user.
