# 001. Unified Graph Memory

## Status
Accepted

## Context
We previously stored "Brain" (Knowledge Graph) and "Soul" (Principles/Values) as separate entities, alongside a flat list of "Memories" (Episodic facts). This fragmentation made it difficult for the Mini to reason holistically about itself. For example, knowing that "I value simplicity" (Soul) should influence how I interpret "I used Go for the backend" (Brain).

## Decision
We will merge the Knowledge Graph and Principles Matrix into a single **Unified Graph Memory**. 

1. **Unified Structure:** 
   - The "Brain" consists of `KnowledgeNode` and `KnowledgeEdge` elements representing semantic knowledge (skills, projects, patterns).
   - The "Soul" consists of `Principle` elements representing behavioral rules and values.
   - While they remain distinct models in code (`KnowledgeGraph` and `PrinciplesMatrix`) for type safety, they are assembled and stored together in the final Memory document.

2. **Storage Format:**
   - The Memory will be stored as a **Markdown document** to remain human-readable and compatible with LLM context windows.
   - **Machine Readability:** To allow the system to rehydrate the full graph structure without parsing natural language Markdown, we will embed the full JSON representation of the graph in a hidden HTML comment at the end of the file:
     ```html
     <!-- GRAPH_DATA_START
     { "graph": { ... }, "principles": { ... } }
     GRAPH_DATA_END -->
     ```

3. **Assembler Logic:**
   - The `MemoryAssembler` will be responsible for merging partial graphs from multiple `ExplorerReport`s.
   - **Conflict Resolution:** 
     - Knowledge Nodes: Merge evidence, take max confidence/depth.
     - Principles: Merge evidence, **average** intensity for duplicate principles (same trigger/action).

## Consequences
- **Positive:** Minis can now "read" their own memory as a structured document or as a graph.
- **Positive:** We preserve the "human-readable" nature of the Mini's identity while enabling complex graph queries in the future.
- **Negative:** The Markdown file size increases due to the embedded JSON. We may need to limit the size of the graph or compress the JSON if it exceeds context limits (though current context windows are large enough).
