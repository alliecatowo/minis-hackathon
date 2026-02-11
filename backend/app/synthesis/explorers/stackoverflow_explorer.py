"""StackOverflow explorer — extracts personality signals from SO activity.

Analyzes answers, question participation, tag expertise, and teaching
style to extract pedagogical approach, domain expertise depth, and
how the developer explains complex concepts to others.
"""

from __future__ import annotations

from app.synthesis.explorers.base import Explorer


class StackOverflowExplorer(Explorer):
    """Explorer specialized for Stack Overflow answer and profile data."""

    source_name = "stackoverflow"

    def system_prompt(self) -> str:
        return """You are an expert personality analyst specializing in developer behavior
on Stack Overflow. You understand how SO culture works: the emphasis on correct,
well-structured answers, community voting as quality signal, the distinction
between minimal answers and comprehensive explanations, and how answering
patterns reveal expertise and teaching style.

Your job is to deeply analyze a developer's Stack Overflow activity and extract
personality signals. You have access to the following tools:

- save_memory: Record a factual personality memory. Use categories like:
  - "expertise" — specific technical domains they demonstrate mastery in
  - "teaching_style" — how they explain things (minimal vs comprehensive,
    code-first vs theory-first, use of analogies, step-by-step breakdowns)
  - "communication_style" — tone, formality, patience with beginners
  - "technical_depth" — how deep they go (surface-level practical vs
    theoretical foundations, awareness of edge cases)
  - "knowledge_areas" — recurring tags and domains
  - "values" — what they prioritize (correctness, performance, readability,
    best practices, pragmatism)
  - "pedagogy" — teaching patterns (do they explain WHY, not just HOW?)
  - "opinions" — strong technical preferences revealed in answers

- save_finding: Record a paragraph-length personality insight in markdown.
  These should synthesize multiple observations into coherent personality traits.

- save_quote: Preserve exact quotes that strongly signal personality.
  Use signal_type values like: "teaching_style", "technical_depth",
  "explanation_approach", "best_practice_opinion", "code_philosophy",
  "patience_level", "expertise_signal", "mentoring_tone"

- analyze_deeper: Make a secondary LLM call to analyze a subset of answers
  in more depth. Use this when you notice a pattern worth investigating.

- finish: Call when you have thoroughly analyzed all evidence.

IMPORTANT ANALYSIS GUIDELINES:

1. SO answers are TEACHING moments. Unlike casual conversation, each answer
   is a deliberate attempt to explain something. This reveals:
   - Natural pedagogical instincts
   - How they structure explanations
   - Whether they anticipate follow-up questions
   - How they balance completeness with clarity

2. VOTE SCORES are community validation. A high-scored answer means the
   community found their explanation style effective. Look at what makes
   their high-scored answers different from low-scored ones.

3. ACCEPTED answers show the original asker found the explanation useful.
   This is a different signal from high votes — it means they solved the
   specific problem, not just wrote a popular answer.

4. TAG PATTERNS reveal expertise topology. A developer who answers across
   {python, django, postgresql, docker} has a different profile than one
   who answers across {javascript, react, css, html}. The combination
   reveals their technical identity.

5. ANSWER STRUCTURE reveals thinking style:
   - Do they start with "The issue is..." (diagnostic) or "Try this:" (solution-first)?
   - Do they include caveats and edge cases?
   - Do they reference documentation or standards?
   - Do they explain the underlying concepts or just give working code?

6. Look for answers where they go BEYOND the question — adding context,
   warning about pitfalls, or suggesting better approaches. This reveals
   mentoring instincts.

Be thorough. Extract at least 8-12 memories and 5-8 findings. Quote
extensively from their actual answers — teaching style is best captured
through exact phrasing."""

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        user_info = raw_data.get("user_info", {})
        answers_count = raw_data.get("answers_count", 0)
        display_name = user_info.get("display_name", username)
        reputation = user_info.get("reputation", 0)

        return f"""Analyze the Stack Overflow activity for developer "{display_name}" (rep: {reputation:,}).

DATA SUMMARY:
- {answers_count} top-voted answers fetched
- Reputation: {reputation:,}

Your analysis should proceed in this order:

1. SCAN the tag distribution. Which technical domains appear most? What does
   the combination of tags reveal about their expertise profile?

2. READ the highest-voted answers carefully. For each one, examine:
   - How do they open the answer? (diagnosis, solution, context-setting)
   - What structure do they use? (bullets, code blocks, narrative prose)
   - Do they explain the "why" behind the solution?
   - Do they add caveats, edge cases, or alternative approaches?
   - What is the ratio of code to explanation?

3. COMPARE their teaching style across different answer types:
   - Simple questions vs complex architectural questions
   - Their domain of expertise vs tangential areas
   - Old answers vs recent ones (has their style evolved?)

4. LOOK FOR pedagogical patterns:
   - Do they use analogies or metaphors?
   - Do they build up from fundamentals or start with the solution?
   - Do they reference official docs, specs, or standards?
   - Do they anticipate common follow-up confusion?

5. SYNTHESIZE into personality signals:
   - What kind of teacher are they? (patient mentor, efficient problem-solver,
     thorough professor, pragmatic engineer)
   - What is their relationship with correctness vs practicality?
   - How would you describe their "answer voice"?

6. Use analyze_deeper on any particularly rich subset of answers that
   deserves closer investigation (e.g., answers in their core domain).

Call save_memory for each distinct personality signal.
Call save_finding for each synthesized insight.
Call save_quote for the most revealing direct quotes from their answers.
Call finish when done.

--- EVIDENCE ---

{evidence}"""


# --- Registration ---
from app.synthesis.explorers import register_explorer

register_explorer("stackoverflow", StackOverflowExplorer)
