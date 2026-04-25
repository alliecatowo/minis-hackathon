# mini-create-local

Create a local/demo AI personality clone ("mini") from repository context. No hosted Minis backend is required.

## Overview

For the concrete local demo slice, use the repository helper first:

```bash
python scripts/minis_claude_plugin_modes.py local-demo --force
```

This gathers local git metadata plus allowlisted repo docs and generates:

- `.claude/agents/<name>-local-mini.md`
- `.claude/minis/<name>-local-mini.evidence.json`

Use the manual/interview flow below only when the user explicitly wants to clone someone else from public GitHub data with `gh`.

## Phase 1: Interview

Ask the user:
1. **Who?** GitHub username
2. **Context?** Colleague, OSS maintainer, team member?
3. **Tools available?** gh CLI, Slack CLI, Glean, blog URL?
4. **Use case?** Code review, pair programming, architecture guidance?

## Phase 2: Discover

Gather evidence using available tools. Always start with GitHub:

```bash
# Profile
! gh api users/{username} --jq '{name, bio, company, blog, public_repos}'

# Top repos by stars
! gh api users/{username}/repos --paginate --jq 'sort_by(-.stargazers_count)[:10] | .[] | {name, description, language, stars: .stargazers_count}'

# Recent commits across repos
! gh api search/commits --jq '.items[:20] | .[] | {repo: .repository.full_name, message: .commit.message, date: .commit.author.date}' -f q="author:{username}" -f sort=author-date

# PRs authored
! gh api search/issues --jq '.items[:15] | .[] | {title, body: .body[:200], repo: .repository_url, state}' -f q="type:pr author:{username}"

# Review comments (how they give feedback)
! gh api search/issues --jq '.items[:10] | .[] | {title, repo: .repository_url}' -f q="commenter:{username} type:pr"
```

If Slack CLI available: `! slack search messages --query "from:{username}" --limit 20`
If blog URL provided: fetch and analyze writing style.

## Phase 3: Synthesize

From gathered evidence, extract:
- **Communication style**: formal/casual, direct/collaborative, concise/detailed
- **Technical values**: architecture preferences, language opinions, patterns they advocate
- **Code review philosophy**: what they approve, what they flag, their tone
- **Personality traits**: mentoring, opinionated, pragmatic, perfectionist, etc.
- **Expertise areas**: languages, frameworks, domains

Write a **soul document** — instructions for how to BE this person:
- Use "You ARE..." not "They are..."
- Include specific examples from evidence
- Capture voice (how they'd phrase things, not just what they'd say)

## Phase 4: Output

Create `.claude/agents/{username}-mini.md`:

```markdown
---
name: {username}-mini
description: AI personality clone of {name} — thinks, writes, and reviews code like them
model: inherit
---

[Soul document as system instructions]

## Context Gathering

When asked to review code or give opinions, first gather relevant context:
- Check the user's GitHub for similar patterns: `! gh api repos/{username}/{repo}/...`
- Search for related discussions they've had
- Consider their known technical values before responding

## Available as @{username}-mini in Claude Code conversations.
```

## Usage

```
/mini-local-demo [display_name]
/mini-create-local <github_username>
```

If the user asks for hosted account evidence, private review history, or account minis, stop local mode and direct them to `/mini-remote-account`. Do not synthesize fake hosted evidence.
