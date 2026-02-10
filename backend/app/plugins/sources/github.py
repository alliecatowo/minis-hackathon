"""GitHub ingestion source plugin — wraps existing github fetch + formatter."""

from __future__ import annotations

from typing import Any

from app.ingestion.formatter import format_evidence
from app.ingestion.github import fetch_github_data
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
