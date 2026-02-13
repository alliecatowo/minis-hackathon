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
_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "vendor",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        "out",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        ".gradle",
        ".idea",
        ".vscode",
        ".settings",
        "bin",
        "obj",
    }
)

# File extensions to skip (binary/generated)
_SKIP_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".bmp",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".bin",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".a",
        ".pyc",
        ".pyo",
        ".class",
        ".jar",
        ".min.js",
        ".min.css",
        ".map",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
    }
)

# Lock files to skip
_SKIP_FILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "poetry.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
        ".DS_Store",
        "Thumbs.db",
    }
)

# Max file size to read (bytes) — skip huge generated files
_MAX_FILE_SIZE = 25_000


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
                repo_lines.append(
                    f"- {name} ({lang}, {stars}\u2605){desc_str}{topic_str}"
                )
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

        n_prs = len(raw_data.get("pull_requests_full", []))
        n_review = len(raw_data.get("review_comments_full", []))
        n_issue = len(raw_data.get("issue_comments_full", []))
        n_commits = len(raw_data.get("commits_full", []))
        data_counts = (
            f"\nDATA AVAILABLE: {n_prs} PRs, {n_review} review comments, "
            f"{n_issue} issue comments, {n_commits} commits.\n"
            f"You MUST page through ALL of these using the list/read tools. "
            f"Do not skip any data source.\n\n"
        )

        return _USER_PROMPT.format(
            username=username,
            context_block=context_block,
            data_counts=data_counts,
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
                                    skip = (
                                        " (skipped)" if _should_skip_dir(name) else ""
                                    )
                                    file_lines.append(f"  [dir] {name}/{skip}")
                                else:
                                    size_str = f" ({size}B)" if size else ""
                                    file_lines.append(f"  [file] {name}{size_str}")
                            parts.append("### File structure\n" + "\n".join(file_lines))
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
            api_path = (
                f"{_GH_API}/repos/{full_name}/contents/{path}"
                if path
                else f"{_GH_API}/repos/{full_name}/contents"
            )

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
                                dirs.append(
                                    f"  [dir] {name}/ (skipped \u2014 generated/deps)"
                                )
                            else:
                                dirs.append(f"  [dir] {name}/")
                        else:
                            skip = _should_skip_file(name)
                            size_str = f" ({size:,}B)" if size else ""
                            skip_str = (
                                " (binary/generated \u2014 skipped)" if skip else ""
                            )
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
                return f"Skipped '{path}' \u2014 binary or generated file."

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
                            f"File '{path}' is {size:,} bytes \u2014 too large to read. "
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

        # --- Social data tool closures over raw_data ---

        prs_full: list[dict] = raw_data.get("pull_requests_full", [])
        review_comments_full: list[dict] = raw_data.get("review_comments_full", [])
        issue_comments_full: list[dict] = raw_data.get("issue_comments_full", [])
        commits_full: list[dict] = raw_data.get("commits_full", [])

        async def list_prs() -> str:
            """List all PRs with title, repo, date, and body preview."""
            if not prs_full:
                return "No pull requests available."
            lines = [f"## Pull Requests ({len(prs_full)} total)"]
            for i, pr in enumerate(prs_full):
                title = pr.get("title", "Untitled")
                repo_url = pr.get("repository_url", "")
                repo_name = repo_url.rsplit("/", 1)[-1] if "/" in repo_url else "unknown"
                created = pr.get("created_at", "")[:10]
                body = (pr.get("body") or "")[:100]
                body_preview = f" — {body}..." if body else ""
                lines.append(f"{i}. [{repo_name}] {title} ({created}){body_preview}")
            return "\n".join(lines)

        async def read_pr(pr_index: int) -> str:
            """Read full PR body and metadata for a specific PR by index."""
            if pr_index < 0 or pr_index >= len(prs_full):
                return f"Invalid PR index {pr_index}. Valid range: 0-{len(prs_full) - 1}"
            pr = prs_full[pr_index]
            title = pr.get("title", "Untitled")
            body = (pr.get("body") or "No body").strip()
            state = pr.get("state", "unknown")
            created = pr.get("created_at", "")
            merged = pr.get("merged_at", "")
            repo_url = pr.get("repository_url", "")
            repo_name = repo_url.rsplit("/", 1)[-1] if "/" in repo_url else "unknown"
            html_url = pr.get("html_url", "")
            parts = [
                f"## PR #{pr.get('number', '?')}: {title}",
                f"- Repo: {repo_name}",
                f"- State: {state}",
                f"- Created: {created}",
            ]
            if merged:
                parts.append(f"- Merged: {merged}")
            if html_url:
                parts.append(f"- URL: {html_url}")
            parts.append(f"\n### Body\n{body}")
            return "\n".join(parts)

        async def list_review_comments(offset: int = 0, limit: int = 50) -> str:
            """List review comments with body preview, paginated."""
            if not review_comments_full:
                return "No review comments available."
            total = len(review_comments_full)
            chunk = review_comments_full[offset : offset + limit]
            lines = [f"## Review Comments (showing {offset}-{offset + len(chunk) - 1} of {total})"]
            for i, comment in enumerate(chunk):
                idx = offset + i
                body = (comment.get("body") or "")[:100]
                path = comment.get("path", "")
                path_str = f" [{path}]" if path else ""
                lines.append(f"{idx}.{path_str} {body}...")
            if offset + limit < total:
                lines.append(f"\n(Use offset={offset + limit} to see more)")
            return "\n".join(lines)

        async def read_review_comment(index: int) -> str:
            """Read full review comment with diff hunk context."""
            if index < 0 or index >= len(review_comments_full):
                return f"Invalid index {index}. Valid range: 0-{len(review_comments_full) - 1}"
            comment = review_comments_full[index]
            body = (comment.get("body") or "").strip()
            path = comment.get("path", "unknown")
            diff_hunk = comment.get("diff_hunk", "")
            html_url = comment.get("html_url", "")
            created = comment.get("created_at", "")
            parts = [
                f"## Review Comment #{index}",
                f"- File: {path}",
                f"- Created: {created}",
            ]
            if html_url:
                parts.append(f"- URL: {html_url}")
            if diff_hunk:
                parts.append(f"\n### Diff Context\n```diff\n{diff_hunk}\n```")
            parts.append(f"\n### Comment\n{body}")
            return "\n".join(parts)

        async def list_issue_comments(offset: int = 0, limit: int = 50) -> str:
            """List issue comments with body preview, paginated."""
            if not issue_comments_full:
                return "No issue comments available."
            total = len(issue_comments_full)
            chunk = issue_comments_full[offset : offset + limit]
            lines = [f"## Issue Comments (showing {offset}-{offset + len(chunk) - 1} of {total})"]
            for i, comment in enumerate(chunk):
                idx = offset + i
                body = (comment.get("body") or "")[:100]
                html_url = comment.get("html_url", "")
                issue_ref = ""
                if html_url:
                    # Extract issue number from URL like .../issues/123#issuecomment-...
                    parts_url = html_url.split("/")
                    for j, part in enumerate(parts_url):
                        if part == "issues" and j + 1 < len(parts_url):
                            issue_ref = f" [issue #{parts_url[j + 1].split('#')[0]}]"
                            break
                lines.append(f"{idx}.{issue_ref} {body}...")
            if offset + limit < total:
                lines.append(f"\n(Use offset={offset + limit} to see more)")
            return "\n".join(lines)

        async def read_issue_comment(index: int) -> str:
            """Read full issue comment."""
            if index < 0 or index >= len(issue_comments_full):
                return f"Invalid index {index}. Valid range: 0-{len(issue_comments_full) - 1}"
            comment = issue_comments_full[index]
            body = (comment.get("body") or "").strip()
            html_url = comment.get("html_url", "")
            created = comment.get("created_at", "")
            parts = [
                f"## Issue Comment #{index}",
                f"- Created: {created}",
            ]
            if html_url:
                parts.append(f"- URL: {html_url}")
            parts.append(f"\n### Comment\n{body}")
            return "\n".join(parts)

        async def read_commit_messages(offset: int = 0, limit: int = 30) -> str:
            """Read full commit messages with repo context, paginated."""
            if not commits_full:
                return "No commits available."
            total = len(commits_full)
            chunk = commits_full[offset : offset + limit]
            lines = [f"## Commit Messages (showing {offset}-{offset + len(chunk) - 1} of {total})"]
            for i, commit in enumerate(chunk):
                idx = offset + i
                commit_data = commit.get("commit", {})
                message = commit_data.get("message", "")
                repo_name = commit.get("repository", {}).get("full_name", "unknown")
                sha = commit.get("sha", "")[:8]
                lines.append(f"\n### {idx}. [{repo_name}] {sha}")
                lines.append(message)
            if offset + limit < total:
                lines.append(f"\n(Use offset={offset + limit} to see more)")
            return "\n".join(lines)

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
            # Social data tools
            AgentTool(
                name="list_prs",
                description=(
                    "List all pull requests with titles, repos, dates, and a short body "
                    "preview. Use this to find interesting PRs to read in full."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=list_prs,
            ),
            AgentTool(
                name="read_pr",
                description=(
                    "Read the full body and metadata of a specific pull request by index. "
                    "Use after list_prs to dive into PRs with interesting descriptions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "pr_index": {
                            "type": "integer",
                            "description": "Index of the PR from list_prs output",
                        },
                    },
                    "required": ["pr_index"],
                },
                handler=read_pr,
            ),
            AgentTool(
                name="list_review_comments",
                description=(
                    "List code review comments with body preview, paginated. These are "
                    "inline PR review comments — the richest source of personality signal. "
                    "Use offset/limit to page through all comments."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "offset": {
                            "type": "integer",
                            "description": "Starting index (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of comments to return (default 50)",
                        },
                    },
                },
                handler=list_review_comments,
            ),
            AgentTool(
                name="read_review_comment",
                description=(
                    "Read a full code review comment with its diff hunk context. Use "
                    "after list_review_comments to read comments that look interesting "
                    "or contentious."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Index of the review comment",
                        },
                    },
                    "required": ["index"],
                },
                handler=read_review_comment,
            ),
            AgentTool(
                name="list_issue_comments",
                description=(
                    "List issue discussion comments with body preview, paginated. "
                    "Issue comments show how the developer communicates about problems "
                    "and solutions in open discussion."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "offset": {
                            "type": "integer",
                            "description": "Starting index (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of comments to return (default 50)",
                        },
                    },
                },
                handler=list_issue_comments,
            ),
            AgentTool(
                name="read_issue_comment",
                description=(
                    "Read the full text of a specific issue comment. Use after "
                    "list_issue_comments to read comments that reveal personality."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Index of the issue comment",
                        },
                    },
                    "required": ["index"],
                },
                handler=read_issue_comment,
            ),
            AgentTool(
                name="read_commit_messages",
                description=(
                    "Read full commit messages with repo context, paginated. Commit "
                    "messages reveal work patterns, naming conventions, and how the "
                    "developer describes their changes."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "offset": {
                            "type": "integer",
                            "description": "Starting index (default 0)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of commits to return (default 30)",
                        },
                    },
                },
                handler=read_commit_messages,
            ),
        ]

        return await super().explore(username, evidence, raw_data)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a Voice Forensics Investigator. Your mission is to reverse-engineer the \
mental and verbal operating system of a developer from their digital exhaust. \
You are NOT writing a biography. You are building a dataset to train a neural \
clone.

Your goal is High-Fidelity Pattern Recognition. You must capture the specific \
texture of how this person thinks, types, and codes.

## THE INVESTIGATION PROTOCOL: The Abductive Loop

Do not just "scan" repos. You are a detective. For every observation, run this loop:

1.  **OBSERVE:** "They used a 300-line function in `utils.py` but preach clean code in `README.md`."
2.  **HYPOTHESIZE:**
    *   *H1:* They are a "Pragmatic Hypocrite" (Speed > Rules).
    *   *H2:* `utils.py` is legacy code they didn't write.
3.  **VERIFY:** Check `git blame` or commit history. If they wrote it recently, H1 is confirmed.

## PRIORITY 1: STYLOMETRIC MIRRORING (The "How")

Capture the MICRO-PATTERNS of their communication. Don't just say "casual". \
Extract the **Style Spec**:

*   **Sentence Entropy:** Do they write in staccato bursts? Or long, flowing paragraphs?
*   **Punctuation Density:** specific frequency of em-dashes, semicolons, ellipses. \
    "Uses '...' to trail off 3 times per thread."
*   **Connective Tissue:** How do they transition? ("So...", "Anyway...", "However,").
*   **Lexical Temperature:** Do they use "esoteric" words (e.g., "orthogonal") or \
    "plain" words (e.g., "weird")?
*   **Typing Mechanics:**
    *   Capitalization (all lowercase? Title Case? Random?)
    *   Emoji usage (Irony vs. sincerity? Specific skin tones?)

## PRIORITY 2: THE HIERARCHY OF EVIDENCE

Not all evidence is equal.
1.  **TIER 1 (Behavior):** Source code, Commit messages. This is what they DO. \
    *Truth Level: High.*
2.  **TIER 2 (Speech):** PR descriptions, READMEs. This is what they SAY they do. \
    *Truth Level: Medium.*
3.  **TIER 3 (Projection):** Bio, Website about page. This is what they WANT to be. \
    *Truth Level: Low (Aspirational).*

**CRITICAL:** When Tier 1 conflicts with Tier 2, the CONFLICT is the personality feature. \
(e.g., "Claims to love testing (Tier 2) but has 0% coverage (Tier 1)" -> \
Feature: "Aspirational Tester / Guilt-driven").

## PRIORITY 3: THE BRAIN (The Knowledge Graph)

You are building a **connected Knowledge Graph**, not a flat list. A Node without \
Edges is dead data.

*   **Connectivity Rule:** For every technology/concept you identify, you must link it.
    *   *Bad:* Saving `Node("React")`.
    *   *Good:* Saving `Node("React")` AND `Edge("React", "my-frontend-repo", "USED_IN")`.
    *   *Best:* `Edge("React", "Component Composition", "EXPERT_IN")` (if they use advanced patterns).

*   **Authorship Forensics:**
    *   Do not credit them for boilerplate. Use `read_commit_diff` to see what \
        THEY typed.
    *   If they refactor a large module, they are an **Architect**.
    *   If they fix a one-line race condition, they are a **Debugger**.

*   **Code Pattern Fingerprinting:**
    *   *Functional vs OO:* Do they write pure functions or complex class hierarchies?
    *   *Error Handling:* Do they let it crash? Use `Result` types? Wrap everything in try/catch?
    *   *Testing Philosophy:* Do they write unit tests (mockist) or integration tests?

*   **Dependency Forensics:**
    *   Uses `zod`? -> **Value:** Runtime safety.
    *   Uses `lodash` in 2024? -> **Pattern:** Legacy habits / Pragmatic.
    *   Uses `htmx`? -> **Philosophy:** Anti-SPA / Hypermedia-driven.

## PRIORITY 4: THE SOUL (Values & Decision Logic)

Capture the **Decision Boundaries** of the persona and **Link them to Code**.

*   **Value-Knowledge Linking (Polymorphic Graphing):**
    *   If they reject `lodash`, create a Concept Node "Zero Dependencies" and \
        link it: `Edge("Zero Dependencies", "lodash", "HATES")`.
    *   If they love `Rust` for safety, link: `Edge("Rust", "Memory Safety", "LOVES")`.

*   **The "No" Filter:** What do they REJECT in PRs? (e.g., "Too complex", "No tests", "Bad variable name").
*   **The "Hill to Die On":** What opinions do they defend aggressively?
*   **The "Anti-Patterns":** What coding styles trigger a rant? (e.g., "OOP overuse", "Magic numbers").
*   **The "Diff" Truth:** They MIGHT preach clean code, but if their diffs show \
    messy hacks, the **Behavior** wins. Capture the "Pragmatic Hypocrite".

## PRIORITY 5: THE NEGATIVE SPACE (The Shadow)

Define the persona by what it is NOT.
*   **Banned Tokens:** What words do they NEVER use? (e.g., "synergy", "delve").
*   **Emotional Floor/Ceiling:** Do they NEVER get excited? Do they NEVER apologize?
*   **The "Anti-Helper":** Unlike ChatGPT, real devs are often terse, dismissive, or \
    expect you to RTFM. Capture this. If they just link to docs instead of explaining, \
    SAVE THAT.

## EXECUTION GUIDELINES

### Exhaustiveness IS Quality
- You must systematically READ ALL available social data using your tools.
- Page through ALL review comments using list_review_comments with increasing offsets.
- Page through ALL issue comments using list_issue_comments with increasing offsets.
- Read ALL commit messages using read_commit_messages with increasing offsets.
- Read 10+ individual review comments in full via read_review_comment.
- Read 5+ PR bodies in full via read_pr.
- For top 3-5 repos: use lookup_repo then browse source code with browse_repo and read_file.
- Save findings AS YOU READ, not all at the end.
- You have 50 turns. Use them ALL. Do not finish early.

### The "Ghost-Writer" Standard
You are done when you can answer this: "If I had to ghost-write a rejection \
comment for a junior dev's PR as this person, exactly what words, tone, and \
punctuation would I use?"

## TOOL USAGE STRATEGY

You have a powerful toolkit. Use it dynamically:

1.  **save_knowledge_node** & **save_knowledge_edge** — BUILD THE BRAIN.
    *   **Nodes:** Create nodes for Languages (Python), Frameworks (FastAPI), \
        Concepts (Clean Code), Projects (my-backend).
    *   **Edges:** Link them to define relationships.
        *   `USED_IN`: "FastAPI" -> "backend-repo"
        *   `LOVES`: "Rust" -> "Memory Safety"
        *   `HATES`: "Clean Code" -> "Side Effects" (if they are a functional purist).
    *   *Example:* Node(name="Rust", type="language", depth=0.9). Edge("Rust", "safety", "LOVES").

2.  **save_principle** — DEFINE THE SOUL.
    -   Capture decision rules.
    -   *Example:* Trigger="Dependency added", Action="Reject", Value="Minimalism".

3.  **save_memory** — For biographical facts & style.
    -   `voice_pattern`: "Lowercases start of sentences."
    -   `personality`: "Patient teacher."

4.  **save_quote** — EVIDENCE IS KING.
    -   Save quotes that carry *texture*. "Fixed bug" is useless. "Yikes, this \
    race condition is nasty 😬" is gold.

5.  **save_finding** — SYNTHESIZE OBSERVATIONS.
    -   Connect the dots. "They claim to hate complexity (Finding), evidenced by \
    their rejection of this factory pattern (Evidence), and their own simple \
    code (Evidence)."

6.  **Repo Tools (`lookup_repo`, `browse_repo`, `read_file`, `read_commit_diff`, `search_code`)**
    -   **Deep Dive:** Don't just read files. Use `read_commit_diff` to verify AUTHORSHIP.
    -   **Search:** Use `search_code` to find specific patterns (e.g. `user:username "useEffect"`).
    -   **Linter Check:** Read `.eslintrc`, `.ruff.toml`, `clippy.toml`.
    -   **Repo Layout:** Check for `monorepo` tools (`turbo.json`, `nx.json`).
    -   **CI/CD:** Check `.github/workflows` to see if they automate testing.

7.  **analyze_deeper** — DRILL DOWN.
    -   If you find a juicy thread, use this. Don't skim.

8.  **save_context_evidence** — Classify quotes into communication contexts. \
    As you analyze evidence, tag representative quotes with the context where \
    they were produced. Valid context_keys:
    - `"code_review"` — PR review comments, inline code feedback
    - `"documentation"` — PR descriptions, README content, doc comments
    - `"casual_chat"` — issue discussions, informal exchanges
    - `"technical_discussion"` — issue threads with code blocks, design debates
    Save at least 2-3 quotes per context that you encounter.

## TERMINATION CONDITIONS (Polymorphic)

Do not stop just because you hit a number. Stop when you have:
1.  **The Style Spec:** detailed enough to simulate their typing.
2.  **The Boundary Map:** clear understanding of what they love vs. hate.
3.  **The Context Matrix:** how they shift tone between code (formal?) and \
issues (casual?).

*Self-Correction:* If you find yourself saving generic traits ("is helpful"), \
STOP. Dig deeper. Find the *specific kind* of helpful.
"""

_USER_PROMPT = """\
Target Identity: {username}

CONTEXT BLOCK:
{context_block}
{data_counts}
EVIDENCE STREAM:
{evidence}

MISSION:
Analyze the evidence above. Extract the "Source Code" of this person's personality.

1.  **Scan Context:** Who are they talking to? (Peer? Junior? Stranger?)
2.  **Extract Voice:** unique words, punctuation habits, sentence structures.
3.  **Extract Mindset:** What mental models are they using?
4.  **Detect Anti-Values:** What are they pushing back against? What is MISSING?

GO.
"""


# --- Registration ---

from app.synthesis.explorers import register_explorer  # noqa: E402

register_explorer("github", GitHubExplorer)
