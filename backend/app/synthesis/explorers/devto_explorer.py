"""Dev.to (devblog) explorer — extracts personality signals from blog articles.

Analyzes published articles, tutorial style, topic choices, and community
engagement to extract the developer's writing voice, technical opinions,
and how they communicate with the broader developer community.
"""

from __future__ import annotations

from app.synthesis.explorers.base import Explorer


class DevToExplorer(Explorer):
    """Explorer specialized for Dev.to article and blog data."""

    source_name = "devblog"

    def system_prompt(self) -> str:
        return """You are an expert personality analyst specializing in developer blogging
behavior. You understand how developer blogs and platforms like Dev.to work:
the motivations behind writing tutorials, opinion pieces, and technical
deep-dives, and how writing choices reveal personality, expertise, and values.

Your job is to deeply analyze a developer's blog articles and extract personality
signals. You have access to the following tools:

- save_memory: Record a factual personality memory. Use categories like:
  - "writing_voice" — their prose style, tone, level of formality, use of
    humor, how they address the reader
  - "expertise" — technical domains they write about with authority
  - "opinions" — technical opinions and strong preferences expressed in articles
  - "teaching_style" — how they structure tutorials, explain concepts, handle
    complexity in written form
  - "interests" — what topics they choose to write about (this is voluntary,
    so it reveals genuine interests)
  - "values" — what they advocate for (DX, testing, accessibility, performance, etc.)
  - "community_engagement" — how they interact with readers, response to comments
  - "content_strategy" — article frequency, topic breadth vs depth, target audience

- save_finding: Record a paragraph-length personality insight in markdown.
  These should synthesize multiple observations into coherent personality traits.

- save_quote: Preserve exact quotes that strongly signal personality.
  Use signal_type values like: "writing_voice", "technical_opinion",
  "teaching_approach", "personal_philosophy", "humor", "advocacy",
  "self_expression", "hot_take", "community_building"

- analyze_deeper: Make a secondary LLM call to analyze a subset of articles
  in more depth. Use this when you notice a pattern worth investigating.

- save_context_evidence: Classify quotes into communication contexts. \
  Dev.to articles are the "public_writing" context — save representative \
  quotes using context_key "public_writing" to capture how they sound in \
  published articles. Save at least 3-5 quotes this way.

- save_knowledge_node: Save a node in the Knowledge Graph for technologies \
  or concepts they write about with expertise. Set depth to reflect their \
  demonstrated knowledge level.
- save_knowledge_edge: Link knowledge nodes (e.g., "React" USED_IN \
  "tutorial-project", "Testing" LOVES "TDD").
- save_principle: Save decision rules or values from their articles (e.g., \
  trigger="choosing a framework", action="evaluate DX first", value="developer experience").

- finish: Call when you have thoroughly analyzed all evidence.

IMPORTANT ANALYSIS GUIDELINES:

1. Blog articles are VOLUNTARY and DELIBERATE. Unlike SO answers (reactive)
   or HN comments (spontaneous), blog posts represent what someone CHOOSES
   to invest time writing about. This is extremely high-signal for personality:
   - Topic selection reveals genuine passions and expertise
   - Writing style is their natural voice, not constrained by platform norms
   - The decision to write at all shows communication motivation

2. ARTICLE TITLES reveal how they think about framing and audience:
   - "How to X" — tutorial-oriented, service mindset
   - "Why X is Better Than Y" — opinionated, willing to take positions
   - "I Built X" — show-and-tell, builder identity
   - "The Problem with X" — critical thinking, industry commentary
   - "X: A Deep Dive" — thoroughness, expertise-sharing

3. WRITING STRUCTURE reveals cognitive style:
   - Do they use lots of code examples or more prose?
   - Short punchy paragraphs or long flowing explanations?
   - Headers and organization style
   - Use of images, diagrams, or visual aids

4. ENGAGEMENT METRICS are social proof:
   - High reactions mean their voice resonates with the community
   - High comment counts mean they write about provocative or helpful topics
   - The ratio of reactions to comments tells you if content is
     "appreciated" (high reactions, low comments) or "debated" (both high)

5. TAGS AND TOPICS across articles reveal their technical identity:
   - Narrow focus = specialist identity
   - Broad range = generalist/polyglot identity
   - Mix of technical and soft-skill topics = holistic developer identity

6. Look for PERSONAL touches — self-deprecating humor, personal anecdotes,
   opinions stated as opinions rather than facts. These are the strongest
   signals of authentic personality.

Be thorough. Extract at least 8-12 memories and 5-8 findings. Quote
extensively from their actual writing — blog prose is the most natural
form of their written voice."""

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        article_count = raw_data.get("article_count", 0)
        articles_meta = raw_data.get("articles", [])

        # Build a quick topic summary from article metadata
        all_tags: dict[str, int] = {}
        total_reactions = 0
        for article in articles_meta:
            for tag in article.get("tags", []):
                all_tags[tag] = all_tags.get(tag, 0) + 1
            total_reactions += article.get("positive_reactions_count", 0)

        top_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]
        tag_summary = ", ".join(f"{tag} ({count})" for tag, count in top_tags)

        return f"""Analyze the Dev.to blog articles for developer "{username}".

DATA SUMMARY:
- {article_count} articles fetched
- Total reactions across all articles: {total_reactions}
- Top tags: {tag_summary or "none available"}

Your analysis should proceed in this order:

1. SCAN the article titles and tags. What topics do they write about?
   Is there a clear focus area or are they a generalist writer?
   What does their choice of topics reveal about their identity?

2. READ the article content carefully. For each article, examine:
   - Opening style: How do they hook the reader?
   - Structure: How do they organize information?
   - Voice: Is it formal, casual, humorous, authoritative?
   - Code vs prose ratio: Are they a "show me the code" or "let me explain" writer?
   - Conclusion style: Do they summarize, call to action, or just stop?

3. COMPARE writing style across articles:
   - Is their voice consistent or does it shift by topic?
   - Tutorial articles vs opinion articles — different persona?
   - How has their writing evolved over time (if dates are available)?

4. ANALYZE engagement patterns:
   - Which articles got the most reactions? What does that tell you?
   - Do they write for beginners, intermediates, or experts?
   - Are they writing to teach, to persuade, or to share?

5. LOOK FOR personality markers:
   - Personal anecdotes or "I" statements
   - Humor style (dad jokes, dry wit, self-deprecation, memes)
   - Strong opinions stated directly vs hedged carefully
   - How they handle nuance and trade-offs
   - References to other developers, tools, or philosophies

6. SYNTHESIZE into personality signals:
   - What is their "writer persona"? (friendly mentor, technical authority,
     opinionated practitioner, enthusiastic explorer)
   - What motivates them to write? (teaching, thought leadership, community
     building, portfolio building, processing ideas)
   - How would you describe their blog voice to someone who has never read them?

7. Use analyze_deeper on any particularly rich article excerpts that
   deserve closer investigation.

Call save_memory for each distinct personality signal.
Call save_finding for each synthesized insight.
Call save_quote for the most revealing direct quotes from their writing.
Call finish when done.

--- EVIDENCE ---

{evidence}"""


# --- Registration ---
from app.synthesis.explorers import register_explorer

register_explorer("devblog", DevToExplorer)
