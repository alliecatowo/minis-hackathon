"""Format raw GitHub data into structured evidence text for LLM analysis."""

from __future__ import annotations

from app.ingestion.github import GitHubData


def format_evidence(data: GitHubData) -> str:
    """Turn raw GitHub API data into a formatted evidence document."""
    sections: list[str] = []

    # User profile summary
    if data.profile:
        sections.append(_format_profile(data.profile))

    # Repos overview
    if data.repos:
        sections.append(_format_repos(data.repos))

    # Commit messages
    if data.commits:
        sections.append(_format_commits(data.commits))

    # PR descriptions
    if data.pull_requests:
        sections.append(_format_prs(data.pull_requests))

    # Code review comments (highest signal for personality)
    if data.review_comments:
        sections.append(_format_review_comments(data.review_comments))

    # Issue discussions
    if data.issue_comments:
        sections.append(_format_issue_comments(data.issue_comments))

    return "\n\n".join(sections)


def _format_profile(profile: dict) -> str:
    name = profile.get("name") or profile.get("login", "Unknown")
    bio = profile.get("bio") or "No bio"
    company = profile.get("company") or "Not specified"
    location = profile.get("location") or "Not specified"
    public_repos = profile.get("public_repos", 0)
    followers = profile.get("followers", 0)

    return f"""## Developer Profile
- **Name**: {name}
- **Bio**: {bio}
- **Company**: {company}
- **Location**: {location}
- **Public repos**: {public_repos}
- **Followers**: {followers}"""


def _format_repos(repos: list[dict]) -> str:
    lines = ["## Top Repositories"]
    for repo in repos[:10]:
        name = repo.get("full_name", repo.get("name", "unknown"))
        desc = repo.get("description") or "No description"
        lang = repo.get("language") or "Unknown"
        stars = repo.get("stargazers_count", 0)
        lines.append(f"- **{name}** ({lang}, {stars} stars): {desc}")
    return "\n".join(lines)


def _format_commits(commits: list[dict]) -> str:
    lines = ["## Commit Messages"]
    lines.append(
        "(These reveal what the developer works on and how they describe changes)\n"
    )
    for commit in commits[:50]:
        commit_data = commit.get("commit", {})
        message = commit_data.get("message", "").split("\n")[0]  # First line only
        repo_name = commit.get("repository", {}).get("full_name", "unknown")
        lines.append(f"- [{repo_name}] {message}")
    return "\n".join(lines)


def _format_prs(prs: list[dict]) -> str:
    lines = ["## Pull Request Descriptions"]
    lines.append(
        "(PR descriptions show how the developer explains and motivates their work)\n"
    )
    for pr in prs[:30]:
        title = pr.get("title", "Untitled")
        body = (pr.get("body") or "").strip()
        repo_url = pr.get("repository_url", "")
        repo_name = repo_url.rsplit("/", 2)[-2:] if "/" in repo_url else ["unknown"]
        repo_label = "/".join(repo_name) if len(repo_name) == 2 else repo_url

        lines.append(f"### [{repo_label}] {title}")
        if body:
            # Truncate very long PR bodies
            if len(body) > 500:
                body = body[:500] + "..."
            lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _format_review_comments(comments: list[dict]) -> str:
    lines = ["## Code Review Comments"]
    lines.append(
        "(HIGHEST SIGNAL: Review comments reveal engineering values, communication style, "
        "and personality — especially when there is disagreement or pushback)\n"
    )
    for comment in comments[:30]:
        body = (comment.get("body") or "").strip()
        if not body:
            continue
        diff_hunk = comment.get("diff_hunk", "")
        path = comment.get("path", "")

        if path:
            lines.append(f"**File: {path}**")
        if diff_hunk:
            # Show last few lines of diff for context
            diff_lines = diff_hunk.strip().split("\n")
            context = "\n".join(diff_lines[-5:]) if len(diff_lines) > 5 else diff_hunk
            lines.append(f"```diff\n{context}\n```")
        lines.append(f"> {body}")
        lines.append("")
    return "\n".join(lines)


def _format_issue_comments(comments: list[dict]) -> str:
    lines = ["## Issue Discussion Comments"]
    lines.append(
        "(Issue comments show how the developer communicates about problems and solutions)\n"
    )
    for comment in comments[:20]:
        body = (comment.get("body") or "").strip()
        if not body:
            continue
        issue_url = comment.get("html_url", "")
        # Truncate long comments
        if len(body) > 400:
            body = body[:400] + "..."
        lines.append(f"- {body}")
        if issue_url:
            lines.append(f"  *Source: {issue_url}*")
        lines.append("")
    return "\n".join(lines)
