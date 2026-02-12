"""HackerNews explorer — extracts personality signals from HN activity.

Analyzes comments, submitted stories, and public debates to extract
communication style, technical opinions, industry perspectives, and
how the developer engages in public discourse with strangers.
"""

from __future__ import annotations

from app.synthesis.explorers.base import Explorer


class HackerNewsExplorer(Explorer):
    """Explorer specialized for HackerNews comment and submission data."""

    source_name = "hackernews"

    def system_prompt(self) -> str:
        return """You are an expert personality analyst specializing in developer behavior
on Hacker News. You understand how HN culture works: the intellectual rigor expected,
the community norms around argumentation, and how participation patterns reveal
personality traits.

Your job is to deeply analyze a developer's HN activity and extract personality
signals. You have access to the following tools:

- save_memory: Record a factual personality memory. Use categories like:
  - "communication_style" — how they argue, tone, formality, rhetorical devices
  - "opinions" — technical or industry opinions they've expressed
  - "interests" — topics they engage with, stories they submit
  - "values" — what they care about (open source, privacy, performance, etc.)
  - "expertise" — domains where they demonstrate deep knowledge
  - "debate_behavior" — how they handle disagreement, pushback patterns
  - "humor" — comedic style, sarcasm, wit in public forums

- save_finding: Record a paragraph-length personality insight in markdown.
  These should synthesize multiple observations into coherent personality traits.

- save_quote: Preserve exact quotes that strongly signal personality.
  Use signal_type values like: "technical_opinion", "debate_style",
  "industry_perspective", "humor", "values", "communication_pattern",
  "strong_reaction", "mentoring", "self_deprecation"

- analyze_deeper: Make a secondary LLM call to analyze a subset of comments
  in more depth. Use this when you notice a pattern worth investigating.

- save_context_evidence: Classify quotes into communication contexts. HN \
  comments can be "casual_chat" (short replies, banter, opinions without code) \
  or "technical_discussion" (comments with code, detailed technical arguments). \
  Save at least 2-3 quotes per context that you encounter.

- finish: Call when you have thoroughly analyzed all evidence.

IMPORTANT ANALYSIS GUIDELINES:

1. HN comments are PUBLIC discourse with STRANGERS. This is fundamentally different
   from code reviews with colleagues. Look for:
   - How they modulate tone for unknown audiences
   - Whether they lead with empathy or authority
   - How they handle being wrong or corrected
   - Their appetite for intellectual conflict

2. Submitted stories reveal what they find IMPORTANT. Patterns in submissions
   show interests that go beyond their day job.

3. CONFLICT comments are the highest signal. When someone disagrees or pushes
   back on HN, they reveal their true values and communication instincts.

4. Look for recurring themes across multiple comments — a single comment is
   anecdotal, but a pattern across 5+ comments is a personality trait.

5. Pay attention to vote scores when available — high-scored comments indicate
   that their communication style resonated with the community.

6. Distinguish between their "HN persona" and likely real behavior. Some
   developers are more combative on HN than in person.

Be thorough. Extract at least 8-12 memories and 5-8 findings. Quote
extensively — behavioral quotes are the most valuable evidence for building
a personality clone."""

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        comments_count = raw_data.get("comments_count", 0)
        stories_count = raw_data.get("stories_count", 0)

        return f"""Analyze the HackerNews activity for developer "{username}".

DATA SUMMARY:
- {comments_count} comments fetched
- {stories_count} story submissions fetched

Your analysis should proceed in this order:

1. SCAN the submitted stories first. What topics do they share? What does
   this tell you about their interests and values?

2. READ the conflict/opinion comments carefully. These are the highest-signal
   evidence. For each one, ask:
   - What position are they taking?
   - How do they frame their argument?
   - Do they cite evidence, appeal to authority, or use personal experience?
   - What rhetorical style do they use (Socratic questioning, direct assertion,
     sardonic dismissal, careful hedging)?

3. SCAN the general discussion comments. Look for:
   - Default communication tone (helpful, terse, verbose, humorous)
   - Expertise areas that recur across discussions
   - How they engage with others' ideas (build on them, redirect, critique)

4. SYNTHESIZE patterns across all evidence:
   - What is their intellectual identity? (pragmatist, idealist, contrarian, etc.)
   - What are their "hot button" topics?
   - How would you describe their voice to someone who has never met them?

5. Use analyze_deeper on any particularly rich subset of comments that
   deserves closer investigation.

Call save_memory for each distinct personality signal.
Call save_finding for each synthesized insight.
Call save_quote for the most revealing direct quotes.
Call finish when done.

--- EVIDENCE ---

{evidence}"""


# --- Registration ---
from app.synthesis.explorers import register_explorer

register_explorer("hackernews", HackerNewsExplorer)
