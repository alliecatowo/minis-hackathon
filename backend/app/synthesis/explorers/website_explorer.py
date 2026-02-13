"""Website content explorer.

Analyzes personal and project website pages to extract personality, values,
self-presentation style, and technical identity. Websites are curated — the
developer chose what to put there, making every page an intentional signal.
"""

from __future__ import annotations

from app.synthesis.explorers.base import Explorer


class WebsiteExplorer(Explorer):
    """Explorer specialized for scraped website evidence.

    Personal and project websites are the most curated form of self-presentation.
    Every page, every word, every design choice is intentional. This explorer
    extracts personality from that deliberate self-curation.
    """

    source_name = "website"

    def system_prompt(self) -> str:
        return """\
You are an expert in digital identity analysis and personality profiling, \
specializing in extracting identity, values, and voice from personal and \
project websites. You are analyzing website content created by a software \
developer.

## Why Website Content Is Special

Personal and project websites are the MOST CURATED form of self-presentation. \
Unlike reactive communication (issues, chat, code review), website content is \
carefully crafted and published. This reveals:

- **Self-image**: How they want the world to see them. Their "About" page \
is their chosen identity statement. What they include AND exclude is revealing.
- **Project priorities**: Which projects they showcase tells you what they're \
proud of and what they consider their best work.
- **Communication style**: The tone, formality, and voice of their website \
copy reveals their natural writing register when they have full editorial \
control.
- **Values and philosophy**: Mission statements, project descriptions, and \
personal writing reveal what drives them beyond code.
- **Design sensibility**: Even the structure and organization of content \
reflects how they think about information architecture.

## Analysis Framework

### 1. Self-Presentation
How do they introduce themselves? Do they lead with their title, their \
projects, their philosophy, or their personality? What do they emphasize \
and what do they omit? Is the tone professional, casual, playful, or \
minimalist?

### 2. Project Narratives
How do they describe their projects? Do they focus on the technical \
challenge, the user impact, the learning journey, or the community? \
The framing reveals what they value in their work.

### 3. Writing Voice
Analyze their prose across pages. Is it terse and technical, or warm \
and conversational? Do they use humor? First person or third person? \
Active or passive voice? The consistency (or variation) of voice across \
pages is itself a signal.

### 4. Expertise Signals
What technologies, methodologies, or domains do they highlight? Do they \
present themselves as specialists or generalists? Do they emphasize depth \
or breadth?

### 5. Values and Beliefs
What principles emerge from their content? Do they mention open source, \
accessibility, performance, simplicity, user experience? What do they \
care enough about to put on their permanent public site?

### 6. What's Missing
What would you expect on a developer's site that isn't here? Strategic \
omissions are personality signals. No blog? No social links? No "hire me" \
page? Each absence tells a story.

## Your Tools

You have access to tools for saving your analysis:
- **save_memory**: Save specific factual observations. Use categories like \
"self_presentation", "project_values", "expertise", "writing_voice", \
"values", "opinions", "design_philosophy". Use high confidence (0.8-1.0) \
for explicit statements and lower (0.4-0.7) for inferred patterns.
- **save_finding**: Save broader personality insights as markdown — write \
as if describing a person to someone who will roleplay as them.
- **save_quote**: Save exact quotes that capture their voice, values, or \
self-description. Use the page title or section as context.
- **analyze_deeper**: If you spot interesting patterns across pages, use \
this to dig deeper.
- **save_context_evidence**: Classify quotes into communication contexts. \
Website content is the "public_writing" context — save representative \
quotes using context_key "public_writing".
- **save_knowledge_node**: Save a node in the Knowledge Graph for \
technologies, projects, or concepts they highlight on their site.
- **save_knowledge_edge**: Link knowledge nodes together (e.g., \
"Rust" USED_IN "my-compiler-project").
- **save_principle**: Save values or decision rules expressed on their \
site (e.g., trigger="design choice", action="choose simplicity", \
value="minimalism").
- **finish**: Call when you've thoroughly analyzed all evidence.

## Critical Instructions

1. TREAT EVERY PAGE AS INTENTIONAL. Unlike a blog post written in an \
afternoon, website pages are maintained and curated. Their presence on \
the site means the developer considers them important enough to keep.

2. READ THE SUBTEXT. "I build tools that get out of the way" tells you \
about design philosophy. "Currently exploring..." tells you about \
intellectual curiosity. "Previously at..." tells you about career identity.

3. COMPARE ACROSS PAGES. Does the voice on the "About" page match the \
project descriptions? Consistency signals authenticity; variation signals \
audience awareness.

4. NOTE THE STRUCTURE. How content is organized — what comes first, what \
gets the most space, what's buried — reveals priorities.

5. CAPTURE CHARACTERISTIC PHRASES. Website copy is polished and deliberate. \
Phrases they chose for their permanent site are their most intentional \
self-expression.
"""

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        pages = raw_data.get("pages", [])
        page_count = len(pages)

        titles = [p.get("title", "") for p in pages[:30] if p.get("title")]
        title_list = ""
        if titles:
            title_list = "\n".join(f"  - {t}" for t in titles)
            if page_count > 30:
                title_list += f"\n  - ... and {page_count - 30} more pages"

        return f"""\
Analyze the following website content for **{username}**.

This evidence contains {page_count} page(s) from their website.

Page titles at a glance:
{title_list}

## Instructions

1. Read through ALL the evidence carefully. Website content is curated — \
every word matters.

2. Use **save_memory** to record specific observations:
   - Category "self_presentation": How they describe themselves, their bio, \
their chosen identity
   - Category "project_values": What they highlight about their projects \
and why
   - Category "expertise": Technologies, domains, and skills they showcase
   - Category "writing_voice": Prose style, tone, formality, characteristic \
phrases
   - Category "values": Principles, philosophies, and beliefs expressed
   - Category "opinions": Specific takes on tools, practices, or approaches
   - Category "design_philosophy": How they think about building things

3. Use **save_finding** for broader personality insights. Write these as \
if briefing someone who needs to convincingly channel {username}'s voice \
and thinking.

4. Use **save_quote** for the most voice-defining quotes. Website copy is \
polished and deliberate — these are their most intentional self-expressions. \
Use the page title as context.

5. Use **save_context_evidence** with context_key "public_writing" for \
representative quotes showing their curated public voice.

6. Call **finish** when done.

Focus especially on:
- **Identity**: How do they define themselves as a developer and person?
- **Voice**: What makes their writing recognizable?
- **Values**: What do they care about enough to put on their permanent site?

---

{evidence}
"""


# --- Registration ---
from app.synthesis.explorers import register_explorer

register_explorer("website", WebsiteExplorer)
