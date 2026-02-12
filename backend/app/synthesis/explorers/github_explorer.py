"""GitHub explorer — analyzes GitHub activity to extract personality signals.

Code reviews, PR descriptions, commit messages, and issue discussions are
the richest source of developer personality data. This explorer is tuned to
find the human behind the code: how they argue, what they defend, what makes
them excited, and how they phrase objections.

The explorer also has tools to browse actual source code in repos, letting it
investigate project structure, coding style, and technical choices directly.
"""

from __future__ import annotations

import base64
import logging
from pathlib import PurePosixPath

import httpx

from app.core.agent import AgentTool
from app.core.config import settings
from app.synthesis.explorers.base import Explorer, ExplorerReport

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"

# Directories to skip when browsing repos
_SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "vendor", "dist", "build", ".next", ".nuxt", "target", "out",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage",
    ".gradle", ".idea", ".vscode", ".settings", "bin", "obj",
})

# File extensions to skip (binary/generated)
_SKIP_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".bin", ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".pyc", ".pyo", ".class", ".jar",
    ".min.js", ".min.css", ".map",
    ".db", ".sqlite", ".sqlite3",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
})

# Lock files to skip
_SKIP_FILES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock",
    "poetry.lock", "Gemfile.lock", "composer.lock", "go.sum",
    ".DS_Store", "Thumbs.db",
})

# Max file size to read (bytes) — skip huge generated files
_MAX_FILE_SIZE = 15_000


def _should_skip_file(name: str) -> bool:
    """Check if a file should be skipped based on name/extension."""
    if name in _SKIP_FILES:
        return True
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in _SKIP_EXTENSIONS:
        return True
    # Skip minified files
    if name.endswith(".min.js") or name.endswith(".min.css"):
        return True
    return False


def _should_skip_dir(name: str) -> bool:
    """Check if a directory should be skipped."""
    return name.lower() in _SKIP_DIRS or name.startswith(".")


def _gh_headers() -> dict[str, str]:
    """Build GitHub API headers."""
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


class GitHubExplorer(Explorer):
    """Explorer specialized for GitHub code collaboration artifacts."""

    source_name = "github"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        # Build context summary from raw_data if available
        context_parts: list[str] = []

        profile = raw_data.get("profile", {})
        if profile:
            name = profile.get("name") or username
            bio = profile.get("bio")
            company = profile.get("company")
            location = profile.get("location")
            context_parts.append(f"Name: {name}")
            if bio:
                context_parts.append(f"Bio: {bio}")
            if company:
                context_parts.append(f"Company: {company}")
            if location:
                context_parts.append(f"Location: {location}")

        repos_summary = raw_data.get("repos_summary", {})
        if repos_summary:
            languages = repos_summary.get("languages", {})
            if languages:
                top_langs = list(languages.keys())[:8]
                context_parts.append(f"Top languages: {', '.join(top_langs)}")
            repo_count = repos_summary.get("repo_count", 0)
            if repo_count:
                context_parts.append(f"Public repos: {repo_count}")

        # Include full repo list so the explorer sees every repo
        all_repos = repos_summary.get("top_repos", [])
        if all_repos:
            repo_lines = []
            for r in all_repos:
                name = r.get("name", "?")
                lang = r.get("language") or "?"
                desc = r.get("description") or ""
                stars = r.get("stargazers_count", 0)
                topics = r.get("topics", [])
                topic_str = f" [{', '.join(topics)}]" if topics else ""
                desc_str = f": {desc[:100]}" if desc else ""
                repo_lines.append(f"- {name} ({lang}, {stars}★){desc_str}{topic_str}")
            context_parts.append(
                f"All {len(all_repos)} repos:\n" + "\n".join(repo_lines)
            )

        context_block = ""
        if context_parts:
            context_block = (
                "### Quick profile summary\n"
                + "\n".join(f"- {p}" for p in context_parts)
                + "\n\n"
            )

        return _USER_PROMPT.format(
            username=username,
            context_block=context_block,
            evidence=evidence,
        )

    async def explore(
        self, username: str, evidence: str, raw_data: dict
    ) -> ExplorerReport:
        """Override to add repo browsing tools for deeper investigation."""
        # Build a lookup of full_name by short name for the tools
        repos_summary = raw_data.get("repos_summary", {})
        all_repos = repos_summary.get("top_repos", [])
        repo_fullnames = {
            r.get("name", ""): r.get("full_name", f"{username}/{r.get('name', '')}")
            for r in all_repos
        }

        def _resolve_repo(repo_name: str) -> str:
            """Resolve short repo name to full_name."""
            return repo_fullnames.get(repo_name, f"{username}/{repo_name}")

        async def lookup_repo(repo_name: str) -> str:
            """Fetch README, file listing, and recent commits for a repo."""
            full_name = _resolve_repo(repo_name)
            headers = _gh_headers()
            parts: list[str] = [f"## Repo overview: {full_name}"]

            async with httpx.AsyncClient(timeout=15.0) as client:
                # Fetch README
                try:
                    resp = await client.get(
                        f"{_GH_API}/repos/{full_name}/readme", headers=headers
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data.get("content", "")
                        if content:
                            readme_text = base64.b64decode(content).decode(
                                "utf-8", errors="replace"
                            )
                            if len(readme_text) > 3000:
                                readme_text = readme_text[:3000] + "\n... (truncated)"
                            parts.append(f"### README\n{readme_text}")
                    else:
                        parts.append("No README found.")
                except Exception:
                    parts.append("Failed to fetch README.")

                # Fetch top-level file listing
                try:
                    resp = await client.get(
                        f"{_GH_API}/repos/{full_name}/contents", headers=headers
                    )
                    if resp.status_code == 200:
                        items = resp.json()
                        if isinstance(items, list):
                            file_lines = []
                            for item in items[:50]:
                                kind = item.get("type", "file")
                                name = item.get("name", "?")
                                size = item.get("size", 0)
                                if kind == "dir":
                                    skip = " (skipped)" if _should_skip_dir(name) else ""
                                    file_lines.append(f"  [dir] {name}/{skip}")
                                else:
                                    size_str = f" ({size}B)" if size else ""
                                    file_lines.append(f"  [file] {name}{size_str}")
                            parts.append(
                                "### File structure\n" + "\n".join(file_lines)
                            )
                except Exception:
                    parts.append("Failed to fetch file listing.")

                # Fetch recent commits
                try:
                    resp = await client.get(
                        f"{_GH_API}/repos/{full_name}/commits",
                        headers=headers,
                        params={"per_page": "10"},
                    )
                    if resp.status_code == 200:
                        commits = resp.json()
                        if isinstance(commits, list) and commits:
                            commit_lines = []
                            for c in commits[:10]:
                                msg = (
                                    c.get("commit", {})
                                    .get("message", "")
                                    .split("\n")[0]
                                )
                                commit_lines.append(f"  - {msg}")
                            parts.append(
                                "### Recent commits\n" + "\n".join(commit_lines)
                            )
                except Exception:
                    pass

            return "\n\n".join(parts)

        async def browse_repo(repo_name: str, path: str = "") -> str:
            """Browse a directory in a repo, showing files and subdirectories."""
            full_name = _resolve_repo(repo_name)
            headers = _gh_headers()
            api_path = f"{_GH_API}/repos/{full_name}/contents/{path}" if path else f"{_GH_API}/repos/{full_name}/contents"

            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    resp = await client.get(api_path, headers=headers)
                    if resp.status_code == 404:
                        return f"Path not found: {path or '/'}"
                    if resp.status_code != 200:
                        return f"Error fetching {path or '/'}: HTTP {resp.status_code}"

                    items = resp.json()
                    if not isinstance(items, list):
                        return f"Path '{path}' is a file, not a directory. Use read_file to read it."

                    lines = [f"## Contents of {full_name}/{path or ''}"]
                    dirs = []
                    files = []

                    for item in items:
                        kind = item.get("type", "file")
                        name = item.get("name", "?")
                        size = item.get("size", 0)

                        if kind == "dir":
                            if _should_skip_dir(name):
                                dirs.append(f"  [dir] {name}/ (skipped — generated/deps)")
                            else:
                                dirs.append(f"  [dir] {name}/")
                        else:
                            skip = _should_skip_file(name)
                            size_str = f" ({size:,}B)" if size else ""
                            skip_str = " (binary/generated — skipped)" if skip else ""
                            files.append(f"  [file] {name}{size_str}{skip_str}")

                    # Show dirs first, then files
                    if dirs:
                        lines.append("### Directories")
                        lines.extend(sorted(dirs))
                    if files:
                        lines.append("### Files")
                        lines.extend(sorted(files))

                    return "\n".join(lines)

                except Exception as e:
                    return f"Failed to browse {path or '/'}: {e}"

        async def read_file(repo_name: str, path: str) -> str:
            """Read the raw content of a source code file from a repo."""
            full_name = _resolve_repo(repo_name)
            headers = _gh_headers()
            filename = PurePosixPath(path).name

            # Pre-check: skip known bad files
            if _should_skip_file(filename):
                return f"Skipped '{path}' — binary or generated file."

            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    resp = await client.get(
                        f"{_GH_API}/repos/{full_name}/contents/{path}",
                        headers=headers,
                    )
                    if resp.status_code == 404:
                        return f"File not found: {path}"
                    if resp.status_code != 200:
                        return f"Error fetching {path}: HTTP {resp.status_code}"

                    data = resp.json()

                    # If it's a directory, tell them to use browse_repo
                    if isinstance(data, list):
                        return f"'{path}' is a directory. Use browse_repo instead."

                    size = data.get("size", 0)
                    if size > _MAX_FILE_SIZE:
                        return (
                            f"File '{path}' is {size:,} bytes — too large to read. "
                            f"Max is {_MAX_FILE_SIZE:,} bytes."
                        )

                    content = data.get("content", "")
                    encoding = data.get("encoding", "")

                    if encoding == "base64" and content:
                        text = base64.b64decode(content).decode(
                            "utf-8", errors="replace"
                        )
                    elif content:
                        text = content
                    else:
                        return f"File '{path}' is empty or has no content."

                    return f"## {full_name}/{path}\n\n```\n{text}\n```"

                except Exception as e:
                    return f"Failed to read {path}: {e}"

        # Inject the extra tools into the base explore() flow
        self._extra_tools = [
            AgentTool(
                name="lookup_repo",
                description=(
                    "Get a quick overview of a repository: README, top-level file "
                    "structure, and recent commits. Use this first to get the lay of "
                    "the land before diving into specific files."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "Short name of the repository (e.g., 'keyboard-firmware')",
                        },
                    },
                    "required": ["repo_name"],
                },
                handler=lookup_repo,
            ),
            AgentTool(
                name="browse_repo",
                description=(
                    "List files and directories at a specific path in a repository. "
                    "Use this to navigate into subdirectories and find interesting "
                    "source code files. Skips binary/generated files automatically."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "Short name of the repository",
                        },
                        "path": {
                            "type": "string",
                            "description": "Path within the repo (e.g., 'src/lib' or '' for root). Defaults to root.",
                        },
                    },
                    "required": ["repo_name"],
                },
                handler=browse_repo,
            ),
            AgentTool(
                name="read_file",
                description=(
                    "Read the raw source code of a file from a repository. Use this "
                    "to examine actual code, config files, Makefiles, etc. to understand "
                    "the developer's coding style, technical choices, and project architecture. "
                    "Automatically skips binary/generated files and enforces size limits."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "repo_name": {
                            "type": "string",
                            "description": "Short name of the repository",
                        },
                        "path": {
                            "type": "string",
                            "description": "Full path to the file within the repo (e.g., 'src/main.c', 'Makefile')",
                        },
                    },
                    "required": ["repo_name", "path"],
                },
                handler=read_file,
            ),
        ]

        return await super().explore(username, evidence, raw_data)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a voice forensics specialist. Your job is to reverse-engineer HOW a \
developer communicates — their typing habits, phrasing patterns, tone, and \
verbal tics — from their GitHub activity and source code. You are building a \
voice profile that will let an AI write EXACTLY like this person.

You are NOT writing a professional bio. You are NOT summarizing their career. \
You are capturing the texture of how they type, talk, argue, joke, and think \
out loud.

## What you are analyzing

Real code collaboration artifacts: pull request reviews, issue discussions, \
commit messages, and repository metadata from GitHub. You also have tools to \
browse and read actual source code from their repositories.

## PRIORITY 1: Voice and typing patterns

This is your most important job. For every piece of text this developer \
wrote, ask yourself: "How would I describe their typing style to someone who \
needs to impersonate them over text?"

### Capitalization and formatting
- Do they use proper capitalization or type in all lowercase?
- Do they capitalize the first word of sentences? Always, sometimes, never?
- Do they use Title Case, ALL CAPS for emphasis, or markdown **bold**?
- Do they use headers, bullet points, numbered lists in PR descriptions?

### Punctuation and sentence structure
- Do they end sentences with periods, or just stop typing?
- Do they use exclamation marks? How often? In what contexts?
- Do they use ellipsis (...)? Em dashes (—)? Parenthetical asides?
- Are their sentences short and punchy, or long and clause-heavy?
- Do they use commas liberally or sparingly?

### Casual vs formal markers
- Do they use contractions (don't, can't) or spell them out?
- Do they use abbreviations (tbh, imo, idk, lgtm, wdyt)?
- Do they use slang, internet speak, or memes?
- Do they use emoji or emoticons? Which ones? How often?
- Do they swear? In what contexts?

### Verbal tics and signature phrases
- Do they have pet phrases they repeat? ("I think", "FWIW", "nit:", etc.)
- How do they start messages? Jump right in, or "Hey," or "So,"?
- How do they end messages? Trailing off, summary, action items?
- Do they hedge ("maybe", "I think", "not sure but") or assert directly?
- Do they use rhetorical questions?

### Message shape and length
- Are their comments typically 1 sentence? 1 paragraph? Multiple paragraphs?
- Do they use line breaks within comments?
- Do commit messages follow conventions or are they freeform?
- Are PR descriptions thorough or minimal?

## PRIORITY 2: Anti-values, dislikes, and DON'Ts

This is just as important as what they DO like. A convincing clone must know \
what this person would NEVER say, NEVER do, and NEVER tolerate.

### What they reject in code reviews
- What patterns do they repeatedly push back on? These are anti-values.
- What makes them visibly frustrated or terse? These are pet peeves.
- What do they refuse to approve? What's a hard blocker for them?
- Do they have "instant reject" triggers (no tests? no docs? bad naming?)

### What they would never do
- What engineering practices would they never adopt?
- What tools, languages, or frameworks do they visibly dislike?
- What communication styles would feel wrong coming from them?
- What opinions would they NEVER express?

### Negative signal examples
- "Please don't..." / "We should never..." / "This is a bad pattern"
- Closing issues with strong disagreement
- Rejecting PRs with specific objections
- Expressing frustration with tools, processes, or patterns

Save these as `"anti_values"` memory entries. The content should be written \
as concrete NEVER/DON'T rules: \
BAD: "Dislikes poorly tested code." \
GOOD: "Would NEVER merge a PR without tests. Has rejected PRs saying things \
like 'where are the tests?' and 'I'm not approving this without at least \
basic coverage'. Testing is non-negotiable."

## PRIORITY 3: Communication personality

### How they handle disagreement
- What exact words do they use when pushing back?
- Do they soften ("nit:", "minor:", "just a thought") or go direct?
- Do they explain WHY they disagree, or just state the objection?
- Do they cite references, link to docs, or argue from first principles?

### Humor and personality texture
- What kind of humor? Dry, self-deprecating, sarcastic, punny, absurdist?
- Do they joke in code reviews or stay professional?
- Do they use humor to soften criticism?
- What are they like as a person, beyond their technical role?

### Collaboration style
- Do they ask questions or make statements?
- Do they offer alternatives when rejecting an approach?
- How do they praise good work? Effusively or sparingly?

## PRIORITY 4: Technical identity and knowledge

### Code reviews reveal values AND anti-values
- What do they nitpick on? These are values.
- What do they let slide? These define the boundary of their values.
- What do they reject outright? These are anti-values.
- What patterns recur across multiple reviews?

### Source code reveals craft
Use the repo exploration tools to examine their actual code:
- Architecture choices, project structure patterns
- Language breadth and domain diversity
- Naming conventions, comment style, error handling approach

## How to use your tools

You have EIGHT tools. Use them methodically:

### Analysis tools (save what you find)

1. **save_memory** — For voice, personality, values, and knowledge. The \
categories are deliberately separated — use the right one:

   **STYLE (how they type):**
   - `"voice_pattern"` — CRITICAL. Concrete typing/style patterns. Write as \
ACTIONABLE VOICE GUIDES, not observations. \
BAD: "Shows a pattern of casual communication." \
GOOD: "Types in all lowercase. Rarely uses periods at end of sentences. \
Starts messages with 'so' or 'yeah' frequently. Uses ':)' but never other \
emoji. Messages are typically 1-2 sentences."
   - `"communication_style"` — Higher-level communication patterns: how they \
structure arguments, handle disagreements, shift tone by context.

   **PERSONALITY (who they are):**
   - `"personality"` — Character traits, temperament, energy, humor style, \
social tendencies. Things that describe who they ARE, not how they type. \
Example: "Deeply patient with newcomers but has zero tolerance for \
laziness. Will spend 30 minutes explaining something to a junior but \
will tersely reject a senior's sloppy PR."

   **VALUES (what they believe and reject):**
   - `"values"` — Engineering principles they actively defend in practice.
   - `"anti_values"` — Things they reject, dislike, or would NEVER do. Write \
as concrete NEVER/DON'T rules with evidence. \
BAD: "Dislikes poorly tested code." \
GOOD: "Would NEVER merge a PR without tests. Has rejected PRs saying \
'where are the tests?' Testing is non-negotiable — this is a hard blocker."
   - `"opinions"` — Specific technical stances with evidence.

   **KNOWLEDGE (what they know and do):**
   - `"projects"` — Repos they maintain or contribute to, with specifics.
   - `"expertise"` — Languages, frameworks, domains.
   - `"workflow"` — How they work (commit style, review approach).
   - `"background"` — Company, role, location if visible.

   Always include `evidence_quote` with the exact words.

2. **save_finding** — For personality narrative discoveries. Write these as \
VOICE GUIDES, not clinical observations. Connect patterns to specific \
evidence. Include findings about what they would NEVER do or say. \
BAD: "Shows a distinctive pattern of using humor to deliver critical feedback." \
GOOD: "Wraps criticism in humor — instead of saying 'this is wrong,' they \
write things like 'lol this is gonna segfault so hard' or 'I love the \
optimism here but have you tried running it'. The humor is dry and \
self-deprecating, never mean-spirited. When they're actually serious about \
a concern, they drop the jokes entirely and write longer, structured comments \
with bullet points." \
Also write DON'T findings: "Would NEVER use corporate jargon or \
buzzwords. No 'synergy', no 'leverage', no 'circle back'. When someone \
uses that language, they respond with dry mockery. Their rejection of \
formality is absolute — even in public-facing docs they keep it casual."

3. **save_quote** — For quotes that show VOICE, not just opinions. Prioritize \
quotes that reveal HOW they talk, not just WHAT they think. A boring factual \
statement is not worth saving. A quote that captures their rhythm, humor, or \
typing style is gold. Always include exact formatting — preserve their \
capitalization, punctuation, emoji, etc. \
ALSO save quotes where they express frustration, rejection, or strong \
negative opinions — these define their anti-values and boundaries. A quote \
like "please never do this" or "I will mass-reject any PR that does X" is \
extremely valuable.

4. **analyze_deeper** — When you find a particularly rich thread or cluster \
that needs more examination.

### Repository exploration tools (investigate codebases)

5. **lookup_repo** — Get a quick overview of a repo: README, file structure, \
recent commits. Start here for any repo that looks interesting.

6. **browse_repo** — Navigate into subdirectories to find interesting source \
code files. Use after lookup_repo to dig deeper.

7. **read_file** — Read actual source code files to understand coding style, \
technical choices, and project architecture.

8. **save_context_evidence** — Classify quotes into communication contexts. \
As you analyze evidence, tag representative quotes with the context where \
they were produced. Valid context_keys:
   - `"code_review"` — PR review comments, inline code feedback
   - `"documentation"` — PR descriptions, README content, doc comments
   - `"casual_chat"` — issue discussions, informal exchanges
   - `"technical_discussion"` — issue threads with code blocks, design debates
Save at least 2-3 quotes per context that you encounter.

9. **finish** — Call this when you've thoroughly analyzed all evidence.

## Exploration strategy

1. Read ALL evidence text first. Focus on HOW things are said, not just what.
2. On your first pass, extract voice patterns: capitalization, punctuation, \
message length, verbal tics, signature phrases, tone. Save at least 3 \
voice_pattern memory entries BEFORE moving to repos.
3. Then look at the repo list. Investigate 3-5 interesting repos using \
lookup_repo, browse_repo, and read_file.
4. Save project/expertise memories with specifics from the code.
5. Circle back to voice — do commit messages and README style reveal \
additional typing patterns?

## Quality standards

- Save at LEAST 3 `voice_pattern` memory entries with concrete typing \
observations (not vague descriptions)
- Save at LEAST 2 `communication_style` memory entries
- Save at LEAST 2 `anti_values` memory entries (things they reject/dislike)
- Save at LEAST 1 `personality` memory entry (who they are as a person)
- Save at least 5-8 total memory entries across knowledge categories \
(projects, expertise, values, opinions, workflow)
- Save at least 3-5 findings written as VOICE GUIDES (include at least 1 \
DON'T finding about what they would never do/say)
- Save at least 3-5 quotes that showcase the developer's VOICE \
(preserve exact formatting, capitalization, emoji, typos) — include at \
least 1 quote showing frustration, rejection, or a strong negative opinion
- Explore at least 3 repos using the repo browsing tools
- Confidence scores: 0.9+ for patterns you see 3+ times, \
0.6-0.8 for patterns you see twice, 0.3-0.5 for single observations
"""

_USER_PROMPT = """\
# Voice forensics: {username}

You are examining the GitHub artifacts of **{username}**. Your primary goal \
is to capture HOW this person communicates — their voice, typing habits, and \
personality texture — so an AI can write exactly like them.

{context_block}\
## Step-by-step instructions

### Step 1: Voice extraction (DO THIS FIRST)

Read through ALL the evidence below. On your first pass, focus entirely on \
typing patterns and voice. Ask yourself these questions and save what you find:

- **Capitalization**: Do they capitalize normally? All lowercase? Inconsistent?
- **Punctuation**: Do they use periods? Exclamation marks? Ellipsis? \
Em dashes? How do they punctuate lists?
- **Message length**: Are comments typically 1 sentence? 1 paragraph? \
Multiple paragraphs with headers?
- **Abbreviations**: Do they use tbh, imo, lgtm, wdyt, ptal, etc.?
- **Emoji/emoticons**: Do they use :), :P, thumbs up emoji, etc.? Which \
ones and how often?
- **Verbal tics**: What words or phrases do they repeat? "I think", "FWIW", \
"nit:", "hmm", "actually", "tbf"?
- **Opening patterns**: How do they start comments? Jump straight in? \
"Hey,", "So,", "@user"?
- **Closing patterns**: How do they end? Trailing off? Summary? \
Action items? No closing at all?
- **Hedging vs asserting**: Do they hedge ("maybe we should", "not sure \
but") or state directly ("this should be X", "change this to Y")?
- **Humor style**: Dry? Self-deprecating? Absurdist? Sarcastic? Punny? \
None?
- **Formality gradient**: How does their tone shift between PR descriptions \
(formal-ish), code reviews (mixed), and issue comments (casual)?

Save at LEAST 3 `voice_pattern` memory entries before moving on. Each one \
should be a concrete, specific observation with evidence quotes.

### Step 2: Anti-values and DON'Ts extraction

Go through the evidence again looking for NEGATIVE signals. What does this \
person reject, dislike, push back against, or refuse to tolerate?

- **Code review rejections**: What patterns do they block PRs for? What \
makes them say "no"?
- **Expressed frustrations**: Where do they sound annoyed, terse, or fed up?
- **Things they would never do**: What engineering practices, communication \
styles, or tools would feel WRONG coming from them?
- **Pet peeves**: What trivial things seem to bother them disproportionately?
- **Anti-patterns they call out**: What do they warn others against?

Save at LEAST 2 `anti_values` memory entries as concrete NEVER/DON'T rules. \
Save quotes showing frustration or rejection — these are high-value.

### Step 3: Conflict and pushback analysis

Look at code review comments, especially any marked as CONFLICT or PUSHBACK. \
Focus on:
- The exact words they use when disagreeing
- Whether they soften criticism or go direct
- How they structure arguments (evidence-first? opinion-first? question-first?)
- Their specific pushback vocabulary

### Step 4: Repository exploration

Look at the repo list and investigate 3-5 interesting repos:
- Use `lookup_repo` to get README, file structure, recent commits
- Use `browse_repo` to navigate into source directories
- Use `read_file` to examine actual code — main entry points, configs, \
core modules
- Pay special attention to repos in unusual languages or personal projects
- Note commit message style — this is voice data too (terse? descriptive? \
conventional commits? freeform?)

Save project/expertise memories with SPECIFIC details from the code.

### Step 5: Knowledge extraction

Save memory entries for factual knowledge:
- `"projects"` — repos with specific details about tech, purpose, stack
- `"expertise"` — languages, frameworks, domains
- `"values"` — engineering principles they defend in practice
- `"opinions"` — specific technical stances with evidence quotes
- `"workflow"` — commit style, review approach, tooling preferences
- `"background"` — company, role, location if visible
- `"personality"` — character traits, temperament, energy, humor type

### Step 6: Finish

Call `finish` when you have:
- At least 3 voice_pattern memories (how they type)
- At least 2 communication_style memories (how they communicate)
- At least 2 anti_values memories (what they reject/dislike)
- At least 1 personality memory (who they are as a person)
- At least 5 total knowledge memories (projects, expertise, values, etc.)
- At least 3 findings written as voice guides (including 1 DON'T finding)
- At least 3 quotes that showcase voice (including 1 rejection/frustration quote)
- Explored at least 3 repos

---

## Evidence

{evidence}
"""


# --- Registration ---

from app.synthesis.explorers import register_explorer  # noqa: E402

register_explorer("github", GitHubExplorer)
