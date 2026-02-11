"""Stack Overflow ingestion source plugin — fetches top answers for personality analysis."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import httpx

from app.plugins.base import IngestionResult, IngestionSource

_API_BASE = "https://api.stackexchange.com/2.3"
_DEFAULT_SITE = "stackoverflow"
_PAGE_SIZE = 50


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities to plain text."""
    text = re.sub(r"<[^>]+>", "", html)
    return unescape(text).strip()


class StackOverflowSource(IngestionSource):
    """Ingestion source that fetches Stack Overflow answers for a user."""

    name = "stackoverflow"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch SO answers and format as evidence.

        Args:
            identifier: Stack Overflow numeric user ID or display name.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            user_id = await self._resolve_user_id(client, identifier)
            user_info = await self._fetch_user_info(client, user_id)
            answers = await self._fetch_top_answers(client, user_id)

        evidence = self._format_evidence(answers, user_info)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "user_id": user_id,
                "user_info": user_info,
                "answers_count": len(answers),
            },
            stats={
                "answers_fetched": len(answers),
                "total_score": sum(a.get("score", 0) for a in answers),
                "accepted_count": sum(1 for a in answers if a.get("is_accepted")),
                "evidence_length": len(evidence),
            },
        )

    async def _resolve_user_id(self, client: httpx.AsyncClient, identifier: str) -> int:
        """Resolve a display name to a numeric user ID, or validate a numeric ID."""
        if identifier.isdigit():
            return int(identifier)

        resp = await client.get(
            f"{_API_BASE}/users",
            params={
                "inname": identifier,
                "site": _DEFAULT_SITE,
                "pagesize": 5,
                "order": "desc",
                "sort": "reputation",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])

        if not items:
            raise ValueError(
                f"No Stack Overflow user found matching '{identifier}'"
            )

        # Prefer exact display_name match (case-insensitive), fall back to top result
        for user in items:
            if user.get("display_name", "").lower() == identifier.lower():
                return user["user_id"]
        return items[0]["user_id"]

    async def _fetch_user_info(self, client: httpx.AsyncClient, user_id: int) -> dict:
        """Fetch basic user profile info."""
        resp = await client.get(
            f"{_API_BASE}/users/{user_id}",
            params={"site": _DEFAULT_SITE},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        return items[0] if items else {}

    async def _fetch_top_answers(
        self, client: httpx.AsyncClient, user_id: int
    ) -> list[dict]:
        """Fetch top-voted answers with full body text."""
        resp = await client.get(
            f"{_API_BASE}/users/{user_id}/answers",
            params={
                "order": "desc",
                "sort": "votes",
                "site": _DEFAULT_SITE,
                "filter": "withbody",
                "pagesize": _PAGE_SIZE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        answers = data.get("items", [])

        # Batch-fetch question titles for all answers
        question_ids = [a["question_id"] for a in answers if "question_id" in a]
        titles = await self._fetch_question_titles(client, question_ids)

        for answer in answers:
            qid = answer.get("question_id")
            answer["_question_title"] = titles.get(qid, "Unknown Question")

        return answers

    async def _fetch_question_titles(
        self, client: httpx.AsyncClient, question_ids: list[int]
    ) -> dict[int, str]:
        """Batch-fetch question titles by ID."""
        if not question_ids:
            return {}

        titles: dict[int, str] = {}
        # SO API accepts semicolon-separated IDs, max ~100 per request
        for i in range(0, len(question_ids), 100):
            batch = question_ids[i : i + 100]
            ids_str = ";".join(str(qid) for qid in batch)
            resp = await client.get(
                f"{_API_BASE}/questions/{ids_str}",
                params={"site": _DEFAULT_SITE},
            )
            resp.raise_for_status()
            data = resp.json()
            for q in data.get("items", []):
                titles[q["question_id"]] = unescape(q.get("title", ""))

        return titles

    def _format_evidence(self, answers: list[dict], user_info: dict) -> str:
        """Format answers into evidence text for LLM personality analysis."""
        display_name = user_info.get("display_name", "Unknown")
        reputation = user_info.get("reputation", 0)

        lines = [
            "## Stack Overflow Answers",
            f"User: {display_name} (Reputation: {reputation:,})",
            "",
            "(SO answers reveal expertise areas, teaching/explanation style, and technical",
            "depth. High-voted answers indicate recognized knowledge.)",
            "",
        ]

        # Collect all tags for a summary
        all_tags: dict[str, int] = {}

        for answer in answers:
            title = answer.get("_question_title", "Unknown Question")
            tags = answer.get("tags", [])
            score = answer.get("score", 0)
            accepted = answer.get("is_accepted", False)
            body_html = answer.get("body", "")
            body_text = _strip_html(body_html)

            for tag in tags:
                all_tags[tag] = all_tags.get(tag, 0) + 1

            tag_str = ", ".join(tags) if tags else "untagged"
            status = f"Score: {score}"
            if accepted:
                status += ", Accepted"

            # Truncate very long answers to keep evidence manageable
            if len(body_text) > 800:
                body_text = body_text[:800] + "..."

            lines.append(f'### Answer to: "{title}" [{tag_str}] ({status})')
            lines.append(f'> "{body_text}"')
            lines.append("")

        # Add tag expertise summary
        if all_tags:
            sorted_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)
            top_tags = [f"{tag} ({count})" for tag, count in sorted_tags[:15]]
            lines.insert(3, f"Top tags: {', '.join(top_tags)}")
            lines.insert(4, "")

        return "\n".join(lines)
