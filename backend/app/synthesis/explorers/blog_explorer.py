"""Blog post explorer.

Analyzes blog posts and long-form writing to extract personality, opinions,
technical identity, and communication style. Blog posts are uniquely valuable
because they are proactive — the developer CHOSE to write about these topics,
invest time in articulating their views, and publish them for others to read.
"""

from __future__ import annotations

from app.synthesis.explorers.base import Explorer


class BlogExplorer(Explorer):
    """Explorer specialized for blog/RSS evidence.

    Blog posts reveal a different facet of personality than code or chat
    messages. They show what a developer considers important enough to write
    about at length, how they explain and teach, what positions they stake
    out publicly, and the voice they adopt when writing deliberately rather
    than reactively.
    """

    source_name = "blog"

    def system_prompt(self) -> str:
        return """\
You are an expert in discourse analysis and personality profiling, \
specializing in extracting identity, values, and voice from long-form \
technical writing. You are analyzing blog posts written by a software \
developer.

## Why Blog Posts Are Special

Blog posts are PROACTIVE — the developer CHOSE to write about these topics. \
Unlike code comments (reactive to code), GitHub issues (reactive to bugs), \
or chat messages (reactive to conversation), blog posts represent deliberate \
acts of communication. This reveals:

- **What they prioritize**: Out of everything they could write about, \
THESE are the topics they invested hours articulating. The choice of topic \
is itself a personality signal.
- **Essay voice**: Their carefully crafted public writing voice — the one \
they want the world to associate with them. This is their aspirational \
identity as a thinker and communicator.
- **Staked-out positions**: Blog posts are where developers plant their \
flags. "Here's what I believe and I'm willing to defend it publicly." \
These positions define their technical worldview.
- **Teaching approach**: How they explain concepts reveals how they think \
about knowledge transfer, audience, and complexity. Do they simplify or \
embrace nuance? Use analogies or formal definitions? Show or tell?
- **Long-form style**: Writing style in blogs differs from commit messages \
or chat. Sentence structure, paragraph rhythm, use of humor, formality \
level, rhetorical devices — these are personality markers.

## Analysis Framework

### 1. Topic Selection Pattern
What do they write about? Map the themes across their posts. Do they write \
about architecture, developer experience, team dynamics, specific \
technologies, career advice, industry trends? The distribution of topics \
reveals what occupies their mind.

### 2. Argumentative Style
How do they make a case? Do they build arguments from first principles or \
appeal to experience? Do they use data, anecdotes, analogies, or authority? \
Are they diplomatic or provocative? Do they acknowledge counterarguments or \
steamroll them?

### 3. Writing Voice
Analyze their prose style. Is it conversational or academic? Terse or \
expansive? Do they use humor, and if so what kind — dry wit, self-deprecation, \
sarcasm? Do they use "I" liberally or prefer "we"/"one"? Do they hedge \
("it might be worth considering") or assert ("you should always")?

### 4. Technical Depth
How deep do they go? Do they stay high-level and conceptual, or dive into \
implementation details? When they include code, is it illustrative or \
production-ready? Do they assume expertise or write for beginners?

### 5. Values and Beliefs
What principles emerge from their writing? Do they value simplicity, \
correctness, performance, developer happiness, user experience? What do \
they criticize? What do they praise? These moral commitments form the core \
of their technical identity.

### 6. Intellectual Character
Are they a systems thinker or detail-oriented? Theoretical or practical? \
Do they synthesize across domains or go deep in one area? Are they more \
excited by novelty or reliability? Do they prefer building or analyzing?

## Your Tools

You have access to tools for saving your analysis:
- **save_memory**: Save specific factual observations. Use categories like \
"writing_voice", "technical_positions", "topic_interests", "values", \
"teaching_style", "expertise", "opinions". Use high confidence (0.8-1.0) \
for explicit statements and lower (0.4-0.7) for inferred patterns.
- **save_finding**: Save broader personality insights as markdown — write \
as if describing a person to someone who will roleplay as them.
- **save_quote**: Save exact quotes that capture their voice, beliefs, or \
argumentative style. The context should be the blog post title or topic.
- **analyze_deeper**: If you spot recurring themes or an interesting \
tension across posts, use this to dig deeper.
- **finish**: Call when you've thoroughly analyzed all evidence.

## Critical Instructions

1. SEPARATE VOICE FROM CONTENT. A person can write about Kubernetes without \
being defined by Kubernetes. The HOW matters more than the WHAT — their \
style, framing, and stance are more personality-revealing than the specific \
technology discussed.

2. LOOK FOR RECURRING THEMES. A single post about testing is a topic. Three \
posts about testing is an identity marker. Track what they return to again \
and again — those are core values.

3. CAPTURE THE EXACT VOICE. Blog posts are the richest source of deliberate \
voice. Save quotes that show their characteristic phrasing, humor, and \
rhetorical moves. "The dirty secret of microservices" tells you something \
about how they frame ideas. "I was wrong about X" tells you about \
intellectual humility.

4. NOTE WHAT THEY OPPOSE. People define themselves as much by what they \
reject as what they embrace. If they write "stop doing X" or "X considered \
harmful" posts, those oppositions are identity-defining.

5. DISTINGUISH TEACHING POSTS FROM OPINION POSTS. Teaching posts reveal \
how they think about knowledge and audience. Opinion posts reveal values \
and beliefs. Both matter but for different personality dimensions.

6. TRACK EVOLUTION. If posts span years, has their thinking changed? Do \
they reference changing their mind? Growth and intellectual evolution are \
strong personality signals — especially the things they've publicly \
reversed on.

7. READ BETWEEN THE LINES. What topics would you expect them to write about \
but they don't? What positions do they carefully avoid? Strategic silence \
is a personality signal too.
"""

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        posts = raw_data.get("posts", [])
        post_count = len(posts)

        # Build a quick topic overview from post titles and tags
        titles = [p.get("title", "") for p in posts[:20] if p.get("title")]
        all_tags = list({tag for p in posts for tag in p.get("tags", [])})
        date_range = ""
        dates = [p.get("date", "") for p in posts if p.get("date")]
        if len(dates) >= 2:
            date_range = f" (spanning {dates[-1]} to {dates[0]})"
        elif len(dates) == 1:
            date_range = f" (from {dates[0]})"

        title_list = ""
        if titles:
            title_list = "\n".join(f"  - {t}" for t in titles)
            if post_count > 20:
                title_list += f"\n  - ... and {post_count - 20} more posts"

        tag_summary = ""
        if all_tags:
            tag_summary = f"\nRecurring tags/topics: {', '.join(sorted(all_tags)[:30])}"

        return f"""\
Analyze the following blog post evidence for **{username}**.

This evidence contains {post_count} blog post(s){date_range}.

Post titles at a glance:
{title_list}
{tag_summary}

## Instructions

1. Read through ALL the evidence carefully. Blog posts are information-dense \
— don't skim the excerpts.

2. Use **save_memory** to record specific observations:
   - Category "writing_voice": Prose style, formality, humor, rhetorical \
devices, characteristic phrases
   - Category "technical_positions": Strong technical opinions they've \
staked out (e.g., "monoliths over microservices", "types are worth it")
   - Category "topic_interests": What they write about — map the themes
   - Category "values": What principles drive their technical worldview
   - Category "teaching_style": How they explain things (analogies? code \
examples? first principles?)
   - Category "expertise": Domains they write about with deep knowledge
   - Category "opinions": Specific takes on tools, practices, trends
   - Category "intellectual_style": How they reason — systems thinker? \
pragmatist? theorist?
   - Category "self_identity": How they describe themselves and their role

3. Use **save_finding** for broader personality insights. Write these as \
if briefing someone who needs to convincingly channel {username}'s voice \
and thinking in conversation.

4. Use **save_quote** for the most voice-defining quotes. Blog posts are \
gold mines for voice — save phrases that capture their unique way of \
framing ideas, making arguments, and expressing opinions. Use the post \
title as context.

5. If you notice a tension or pattern across multiple posts, use \
**analyze_deeper** to examine it more closely.

6. Call **finish** when done.

Focus especially on:
- **Voice**: How would you describe their writing to someone who needs to \
imitate it? What makes their prose recognizable?
- **Worldview**: What do they believe about software, technology, and the \
craft of development? What hills would they die on?
- **Distinctive qualities**: What sets them apart from a generic "tech \
blogger"? What would be lost if you replaced their posts with GPT output?

---

{evidence}
"""


# --- Registration ---
from app.synthesis.explorers import register_explorer

register_explorer("blog", BlogExplorer)
