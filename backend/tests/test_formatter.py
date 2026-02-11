"""Tests for backend/app/ingestion/formatter.py."""

from __future__ import annotations

from app.ingestion.formatter import (
    _format_language_profile,
    _format_profile,
    _format_repos,
)
from app.ingestion.github import GitHubData


# ── _format_profile ──────────────────────────────────────────────────


class TestFormatProfile:
    def test_basic_profile(self):
        profile = {
            "name": "Linus Torvalds",
            "login": "torvalds",
            "bio": "Creator of Linux and Git",
            "company": "Linux Foundation",
            "location": "Portland, OR",
            "public_repos": 7,
            "followers": 200000,
        }
        result = _format_profile(profile)
        assert "Linus Torvalds" in result
        assert "Creator of Linux and Git" in result
        assert "Linux Foundation" in result
        assert "Portland, OR" in result
        assert "7" in result
        assert "200000" in result
        assert "## Developer Profile" in result

    def test_missing_fields_use_defaults(self):
        profile = {"login": "ghost"}
        result = _format_profile(profile)
        assert "ghost" in result
        assert "No bio" in result
        assert "Not specified" in result

    def test_name_falls_back_to_login(self):
        profile = {"login": "testuser"}
        result = _format_profile(profile)
        assert "testuser" in result


# ── _format_repos ────────────────────────────────────────────────────


class TestFormatRepos:
    def test_basic_repo_formatting(self):
        repos = [
            {
                "full_name": "user/project",
                "name": "project",
                "description": "A cool project",
                "language": "Python",
                "stargazers_count": 42,
                "topics": ["cli", "python"],
            }
        ]
        result = _format_repos(repos)
        assert "## Top Repositories" in result
        assert "user/project" in result
        assert "Python" in result
        assert "42 stars" in result
        assert "A cool project" in result
        assert "cli, python" in result

    def test_repos_with_no_description(self):
        repos = [
            {
                "name": "empty",
                "language": "Rust",
                "stargazers_count": 0,
            }
        ]
        result = _format_repos(repos)
        assert "No description" in result

    def test_more_than_15_repos_shows_catalog(self):
        repos = []
        for i in range(20):
            repos.append({
                "full_name": f"user/repo-{i}",
                "name": f"repo-{i}",
                "description": f"Repo number {i}",
                "language": "Go",
                "stargazers_count": i,
                "topics": [],
            })
        result = _format_repos(repos)
        assert "## Top Repositories" in result
        assert "Complete Repository Catalog" in result
        assert "20 total" in result
        # First 15 in top section, remaining 5 in catalog
        assert "repo-0" in result
        assert "repo-19" in result

    def test_topics_appear_in_brackets(self):
        repos = [
            {
                "name": "project",
                "language": "TypeScript",
                "stargazers_count": 10,
                "topics": ["react", "nextjs"],
            }
        ]
        result = _format_repos(repos)
        assert "[react, nextjs]" in result


# ── _format_language_profile ─────────────────────────────────────────


class TestFormatLanguageProfile:
    def test_language_aggregation(self):
        repos = [
            {"full_name": "user/a", "name": "a", "language": "Python", "topics": []},
            {"full_name": "user/b", "name": "b", "language": "Python", "topics": []},
            {"full_name": "user/c", "name": "c", "language": "Rust", "topics": []},
        ]
        result = _format_language_profile(repos, {})
        assert "## Technical Profile" in result
        assert "Python" in result
        assert "Rust" in result
        # Python should have 2 repos
        assert "Python: 2 repos" in result

    def test_per_repo_language_data(self):
        repos = [
            {"full_name": "user/web", "name": "web", "language": "TypeScript", "topics": []},
        ]
        repo_languages = {
            "user/web": {"TypeScript": 50000, "JavaScript": 10000, "CSS": 5000},
        }
        result = _format_language_profile(repos, repo_languages)
        assert "TypeScript" in result
        assert "JavaScript" in result
        assert "CSS" in result

    def test_topics_aggregation(self):
        repos = [
            {"full_name": "user/a", "name": "a", "language": "Python", "topics": ["cli", "python"]},
            {"full_name": "user/b", "name": "b", "language": "Python", "topics": ["cli", "api"]},
        ]
        result = _format_language_profile(repos, {})
        assert "Technology Stack" in result
        assert "cli (2)" in result

    def test_empty_repos(self):
        result = _format_language_profile([], {})
        assert "## Technical Profile" in result
