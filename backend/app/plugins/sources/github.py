"""GitHub ingestion source plugin — wraps existing github fetch + formatter."""

from __future__ import annotations

from typing import Any

from app.ingestion.formatter import format_evidence
from app.ingestion.github import GitHubData, fetch_github_data
from app.plugins.base import IngestionResult, IngestionSource


class GitHubSource(IngestionSource):
    """Ingestion source that fetches GitHub activity for a username."""

    name = "github"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch GitHub data and format as evidence.

        Args:
            identifier: GitHub username.
        """
        github_data = await fetch_github_data(identifier)
        evidence = format_evidence(github_data)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "profile": github_data.profile,
                "repos_summary": {
                    "languages": _aggregate_languages(github_data),
                    "repo_count": len(github_data.repos),
                    "top_repos": [
                        {
                            "name": r.get("name"),
                            "description": r.get("description"),
                            "language": r.get("language"),
                        }
                        for r in github_data.repos[:10]
                    ],
                },
            },
            stats={
                "repos_count": len(github_data.repos),
                "commits_analyzed": len(github_data.commits),
                "prs_analyzed": len(github_data.pull_requests),
                "reviews_analyzed": len(github_data.review_comments),
                "issue_comments_analyzed": len(github_data.issue_comments),
                "evidence_length": len(evidence),
            },
        )


def _aggregate_languages(github_data: GitHubData) -> dict[str, int]:
    """Aggregate language byte counts across all repos into a sorted summary."""
    totals: dict[str, int] = {}
    for lang_map in github_data.repo_languages.values():
        for lang, byte_count in lang_map.items():
            totals[lang] = totals.get(lang, 0) + byte_count
    # Sort by bytes descending
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))
