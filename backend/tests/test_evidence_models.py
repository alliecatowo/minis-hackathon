"""Tests for evidence and explorer progress models.

These tests verify model construction and default values without
requiring a database connection.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.core.evidence_access import evidence_export_block_reason, evidence_is_exportable
from app.models.evidence import (
    Evidence,
    ExplorerFinding,
    ExplorerProgress,
    ExplorerQuote,
    ReviewCycle,
)


class TestEvidenceModel:
    def test_create_evidence(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="fix: resolve null pointer in auth module",
            context="commit_message",
        )
        assert ev.source_type == "github"
        assert ev.item_type == "commit"
        assert ev.content == "fix: resolve null pointer in auth module"
        assert ev.context == "commit_message"

    def test_evidence_explored_column_default(self):
        """Column default for explored is False (applied at DB insert time)."""
        col = Evidence.__table__.columns["explored"]
        assert col.default.arg is False

    def test_evidence_metadata_json_nullable(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="hackernews",
            item_type="comment",
            content="A comment",
            context="hackernews_comment",
            metadata_json={"url": "https://example.com", "score": 42},
        )
        assert ev.metadata_json["url"] == "https://example.com"
        assert ev.metadata_json["score"] == 42

    def test_evidence_metadata_json_default_none(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="pr",
            content="PR description",
        )
        assert ev.context is None
        assert ev.metadata_json is None

    def test_evidence_tablename(self):
        assert Evidence.__tablename__ == "evidence"

    def test_evidence_source_privacy_column_default(self):
        """source_privacy column default is 'public' (applied at DB insert time)."""
        col = Evidence.__table__.columns["source_privacy"]
        assert col.default.arg == "public"

    def test_evidence_source_privacy_can_be_set_to_private(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="claude_code",
            item_type="conversation",
            content="User said: let's use async/await everywhere",
            context="private_chat",
            source_privacy="private",
        )
        assert ev.context == "private_chat"
        assert ev.source_privacy == "private"

    def test_evidence_source_privacy_public(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="fix: resolve null pointer",
            context="commit_message",
            source_privacy="public",
        )
        assert ev.context == "commit_message"
        assert ev.source_privacy == "public"

    def test_evidence_context_column_default(self):
        col = Evidence.__table__.columns["context"]
        assert col.default.arg == "general"

    def test_review_grade_envelope_fields_can_be_set(self):
        source_time = datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc)
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="review",
            content="Comment:\nPlease keep this scoped to the retry path.",
            context="code_review",
            source_uri="https://github.com/acme/app/pull/7#discussion_r1",
            author_id="github:reviewer",
            audience_id="github:author",
            target_id="github:author",
            scope_json={"type": "repo", "id": "acme/app", "path": "app/retry.py"},
            raw_body="Please keep this scoped to the retry path.",
            raw_body_ref="github:discussion_r1",
            raw_context_json={
                "ref": "github:pull/7/thread/1",
                "path": "app/retry.py",
                "diff_hunk": "@@ -1,3 +1,5 @@",
            },
            provenance_json={"collector": "github", "confidence": 1.0},
            retention_policy="standard",
            source_authorization="authorized",
            access_classification="company",
            lifecycle_audit_json={"granted_by": "github_oauth", "ticket": "MINI-223"},
            evidence_date=source_time,
        )

        envelope = ev.provenance_envelope()
        assert envelope["source_uri"] == "https://github.com/acme/app/pull/7#discussion_r1"
        assert envelope["author_id"] == "github:reviewer"
        assert envelope["audience_id"] == "github:author"
        assert envelope["scope"] == {"type": "repo", "id": "acme/app", "path": "app/retry.py"}
        assert envelope["timestamp"] == source_time
        assert envelope["raw_excerpt"] == "Please keep this scoped to the retry path."
        assert envelope["surrounding_context_ref"] == "github:pull/7/thread/1"
        assert envelope["provenance_confidence"] == 1.0
        assert envelope["retention_policy"] == "standard"
        assert envelope["source_authorization"] == "authorized"
        assert envelope["access_classification"] == "company"
        assert envelope["lifecycle_audit"] == {"granted_by": "github_oauth", "ticket": "MINI-223"}

    def test_minimal_legacy_evidence_has_explicit_missing_envelope_values(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="fix: preserve existing behavior",
        )

        envelope = ev.provenance_envelope()
        assert envelope["source_uri"] is None
        assert envelope["author_id"] is None
        assert envelope["audience_id"] is None
        assert envelope["scope"] is None
        assert envelope["timestamp"] is None
        assert envelope["raw_excerpt"] == "fix: preserve existing behavior"
        assert envelope["provenance_confidence"] is None
        assert envelope["retention_policy"] is None
        assert envelope["source_authorization"] is None
        assert envelope["access_classification"] is None

    def test_source_authorized_company_evidence_is_exportable(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="review",
            content="Please keep auth boundaries explicit.",
            source_privacy="public",
            retention_policy="standard",
            source_authorization="authorized",
            access_classification="company",
            retention_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )

        assert evidence_is_exportable(ev)
        assert evidence_export_block_reason(ev) is None

    def test_private_evidence_fails_closed_for_export(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="claude_code",
            item_type="conversation",
            content="Private local session",
            source_privacy="private",
            retention_policy="standard",
            source_authorization="authorized",
            access_classification="private",
        )

        assert not evidence_is_exportable(ev)
        assert evidence_export_block_reason(ev) == "private_source"

    def test_missing_or_revoked_policy_fails_closed_for_export(self):
        missing = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="review",
            content="Legacy evidence",
            source_privacy="public",
        )
        revoked = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="review",
            content="Revoked evidence",
            source_privacy="public",
            retention_policy="standard",
            source_authorization="revoked",
            access_classification="company",
        )

        assert evidence_export_block_reason(missing) == "missing_retention_policy"
        assert evidence_export_block_reason(revoked) == "source_not_authorized"


class TestExplorerFindingModel:
    def test_create_finding(self):
        f = ExplorerFinding(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            category="personality",
            content="Developer is meticulous about code review",
        )
        assert f.source_type == "github"
        assert f.category == "personality"
        assert f.content == "Developer is meticulous about code review"

    def test_finding_confidence_column_default(self):
        """Column default for confidence is 0.5 (applied at DB insert time)."""
        col = ExplorerFinding.__table__.columns["confidence"]
        assert col.default.arg == 0.5

    def test_finding_custom_confidence(self):
        f = ExplorerFinding(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="stackoverflow",
            category="skills",
            content="Expert in Python async",
            confidence=0.95,
        )
        assert f.confidence == 0.95

    def test_finding_tablename(self):
        assert ExplorerFinding.__tablename__ == "explorer_findings"


class TestExplorerQuoteModel:
    def test_create_quote(self):
        q = ExplorerQuote(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            quote="I'd rather have no abstraction than the wrong abstraction.",
            context="PR review comment on over-engineered factory pattern",
            significance="Shows preference for simplicity",
        )
        assert q.quote == "I'd rather have no abstraction than the wrong abstraction."
        assert q.context is not None
        assert q.significance is not None

    def test_quote_optional_fields(self):
        q = ExplorerQuote(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="hackernews",
            quote="Just ship it.",
        )
        assert q.context is None
        assert q.significance is None

    def test_quote_tablename(self):
        assert ExplorerQuote.__tablename__ == "explorer_quotes"


class TestExplorerProgressModel:
    def test_create_progress(self):
        p = ExplorerProgress(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
        )
        assert p.source_type == "github"

    def test_progress_count_column_defaults(self):
        """All count columns default to 0 (applied at DB insert time)."""
        table = ExplorerProgress.__table__
        for col_name in (
            "total_items",
            "explored_items",
            "findings_count",
            "memories_count",
            "quotes_count",
            "nodes_count",
        ):
            col = table.columns[col_name]
            assert col.default.arg == 0, f"{col_name} default should be 0"

    def test_progress_status_column_default(self):
        """Status column defaults to 'pending' (applied at DB insert time)."""
        col = ExplorerProgress.__table__.columns["status"]
        assert col.default.arg == "pending"

    def test_progress_optional_timestamps(self):
        p = ExplorerProgress(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
        )
        assert p.started_at is None
        assert p.finished_at is None
        assert p.summary is None

    def test_progress_custom_values(self):
        p = ExplorerProgress(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            total_items=100,
            explored_items=50,
            findings_count=12,
            status="in_progress",
            summary="Halfway through analysis",
        )
        assert p.total_items == 100
        assert p.explored_items == 50
        assert p.findings_count == 12
        assert p.status == "in_progress"
        assert p.summary == "Halfway through analysis"

    def test_progress_tablename(self):
        assert ExplorerProgress.__tablename__ == "explorer_progress"


class TestReviewCycleModel:
    def test_create_review_cycle(self):
        cycle = ReviewCycle(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            external_id="repo:123:allie:deadbeef",
            predicted_state={
                "private_assessment": {"blocking_issues": [], "non_blocking_issues": []},
                "expressed_feedback": {"summary": "", "comments": []},
            },
        )
        assert cycle.source_type == "github"
        assert cycle.external_id == "repo:123:allie:deadbeef"
        assert cycle.predicted_state["private_assessment"]["blocking_issues"] == []
        assert cycle.human_review_outcome is None
        assert cycle.delta_metrics is None

    def test_review_cycle_source_type_default(self):
        col = ReviewCycle.__table__.columns["source_type"]
        assert col.default.arg == "github"

    def test_review_cycle_tablename(self):
        assert ReviewCycle.__tablename__ == "review_cycles"
