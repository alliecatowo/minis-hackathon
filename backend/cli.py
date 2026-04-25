"""Minis CLI — dev convenience tool for managing minis locally."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from enum import Enum

import httpx
import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text as RichText

# Add backend to path to allow importing app
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from sqlalchemy import select
from app.db import async_session
from app.models.mini import Mini
from app.models.evidence import ReviewCycle

API_BASE = "http://localhost:8000/api"
DB_PATH = os.path.join(os.getcwd(), "minis.db")

app = typer.Typer(help="Minis CLI — manage your developer personality clones.")
db_app = typer.Typer(help="Database operations.")
app.add_typer(db_app, name="db")

console = Console()


class ReviewAuthorModel(str, Enum):
    junior_peer = "junior_peer"
    trusted_peer = "trusted_peer"
    senior_peer = "senior_peer"
    unknown = "unknown"


class ReviewDeliveryContext(str, Enum):
    hotfix = "hotfix"
    normal = "normal"
    exploratory = "exploratory"
    incident = "incident"


def _auth_headers() -> dict[str, str]:
    """Get auth headers from MINIS_TOKEN env var."""
    token = os.environ.get("MINIS_TOKEN", "")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _run_git(args: list[str], cwd: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return completed.stdout.strip()


def _try_git(args: list[str], cwd: str | None = None) -> str | None:
    try:
        return _run_git(args, cwd=cwd)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _resolve_repo_name() -> str | None:
    remote_url = _try_git(["remote", "get-url", "origin"])
    if not remote_url:
        return os.path.basename(os.getcwd()) or None

    normalized = remote_url.rstrip("/")
    if "github.com/" in normalized:
        normalized = normalized.split("github.com/", 1)[1]
    elif ":" in normalized and normalized.startswith("git@"):
        normalized = normalized.split(":", 1)[1]

    normalized = normalized.removesuffix(".git").strip("/")
    if "/" not in normalized:
        return os.path.basename(os.getcwd()) or None
    return normalized


def _detect_base_ref() -> str | None:
    candidates = [
        _try_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]),
        "origin/main",
        "origin/master",
        "main",
        "master",
    ]
    seen: set[str] = set()
    for ref in candidates:
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if _try_git(["rev-parse", "--verify", ref]):
            return ref
    return None


def _collect_pre_review_request(
    *,
    base_ref: str | None,
    title: str | None,
    description: str | None,
    author_model: ReviewAuthorModel,
    delivery_context: ReviewDeliveryContext,
) -> tuple[str, dict[str, object]]:
    resolved_base = base_ref or _detect_base_ref()
    if not resolved_base:
        raise RuntimeError(
            "Could not determine a base ref. Pass --base explicitly, for example --base origin/main."
        )

    try:
        merge_base = _run_git(["merge-base", "HEAD", resolved_base])
        changed_files_raw = _run_git(
            ["diff", "--name-only", "--diff-filter=ACMRD", "--find-renames", merge_base]
        )
        untracked_files_raw = _run_git(["ls-files", "--others", "--exclude-standard"])
        diff_summary = _run_git(["diff", "--stat", "--find-renames", merge_base])
        branch_name = _try_git(["branch", "--show-current"]) or "current-branch"
    except FileNotFoundError as exc:
        raise RuntimeError("Git is required for pre-review, but it is not installed.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"Unable to read git diff context: {stderr}") from exc

    changed_files = [line.strip() for line in changed_files_raw.splitlines() if line.strip()]
    untracked_files = [line.strip() for line in untracked_files_raw.splitlines() if line.strip()]
    changed_files = list(dict.fromkeys([*changed_files, *untracked_files]))
    if untracked_files:
        untracked_summary = "Untracked files:\n" + "\n".join(untracked_files[:50])
        diff_summary = "\n\n".join(part for part in [diff_summary, untracked_summary] if part)

    if not changed_files and not diff_summary:
        raise RuntimeError(
            "No local changes found for pre-review. Commit or edit something first, or pass a different --base."
        )

    request = {
        "repo_name": _resolve_repo_name(),
        "title": title or f"Pre-review: {branch_name}",
        "description": description or f"Working tree diff against {resolved_base}.",
        "diff_summary": diff_summary[:50000],
        "changed_files": changed_files[:200],
        "author_model": author_model.value,
        "delivery_context": delivery_context.value,
    }
    return resolved_base, request


def _approval_style(approval_state: str) -> str:
    if approval_state == "approve":
        return "green"
    if approval_state == "comment":
        return "yellow"
    return "red"


def _review_prediction_unavailable_reason(prediction: dict[str, object]) -> str | None:
    required = {"prediction_available", "mode", "unavailable_reason"}
    if not required.issubset(prediction):
        return "backend response omitted review prediction availability contract"

    if prediction.get("prediction_available") is False or prediction.get("mode") == "gated":
        return str(prediction.get("unavailable_reason") or "review prediction is gated")

    if prediction.get("prediction_available") is not True:
        return "backend response returned invalid prediction_available value"
    if prediction.get("mode") != "llm":
        return f"backend response returned unsupported review prediction mode: {prediction.get('mode')}"
    if prediction.get("unavailable_reason") is not None:
        return "backend response returned unavailable_reason for available prediction"
    return None


def _render_pre_review_report(username: str, base_ref: str, prediction: dict[str, object]) -> None:
    unavailable_reason = _review_prediction_unavailable_reason(prediction)
    if unavailable_reason:
        console.print(
            Panel(
                RichText.assemble(
                    ("Mini: ", "dim"),
                    (f"{username}\n", "bold cyan"),
                    ("Base: ", "dim"),
                    (f"{base_ref}\n", "bold white"),
                    ("Prediction: ", "dim"),
                    ("unavailable", "bold yellow"),
                ),
                title="Pre-review gated",
                border_style="yellow",
            )
        )
        console.print(f"[yellow]No review prediction was produced:[/yellow] {unavailable_reason}")
        return

    private_assessment = prediction.get("private_assessment", {})
    expressed_feedback = prediction.get("expressed_feedback", {})
    delivery_policy = prediction.get("delivery_policy", {})
    blockers = private_assessment.get("blocking_issues", []) or []
    open_questions = private_assessment.get("open_questions", []) or []
    approval_state = str(expressed_feedback.get("approval_state") or "unknown")

    summary = expressed_feedback.get("summary") or "No summary returned."
    strictness = delivery_policy.get("strictness") or "unknown"

    console.print(
        Panel(
            RichText.assemble(
                ("Mini: ", "dim"),
                (f"{username}\n", "bold cyan"),
                ("Base: ", "dim"),
                (f"{base_ref}\n", "bold white"),
                ("Likely verdict: ", "dim"),
                (approval_state.replace("_", " "), f"bold {_approval_style(approval_state)}"),
                ("\nStrictness: ", "dim"),
                (str(strictness), "bold white"),
            ),
            title="Pre-review",
            border_style="blue",
        )
    )
    console.print(f"[bold]Summary:[/bold] {summary}")

    if blockers:
        table = Table(title="Likely blockers")
        table.add_column("Key", style="cyan")
        table.add_column("Confidence", justify="right")
        table.add_column("Summary")
        table.add_column("Framework")
        for blocker in blockers:
            confidence = blocker.get("confidence")
            confidence_str = (
                f"{float(confidence):.0%}" if isinstance(confidence, int | float) else "—"
            )
            framework_id = blocker.get("framework_id")
            revision = blocker.get("revision")
            if framework_id:
                if isinstance(revision, int) and revision > 0:
                    framework_str = f"from framework: {framework_id}, validated {revision}×"
                else:
                    framework_str = f"from framework: {framework_id}"
            else:
                framework_str = ""
            table.add_row(
                str(blocker.get("key") or "unknown"),
                confidence_str,
                str(blocker.get("summary") or ""),
                framework_str,
            )
        console.print(table)
    else:
        console.print("[green]No likely blockers surfaced by this mini.[/green]")

    if open_questions:
        console.print("[bold]Open questions:[/bold]")
        for question in open_questions[:5]:
            console.print(f"- {question.get('summary') or question.get('rationale') or 'Unknown question'}")


def _render_patch_advisor_report(username: str, base_ref: str, advisor: dict[str, object]) -> None:
    if advisor.get("advice_available") is False or advisor.get("mode") == "gated":
        reason = advisor.get("unavailable_reason") or "patch advisor is gated"
        console.print(
            Panel(
                RichText.assemble(
                    ("Mini: ", "dim"),
                    (f"{username}\n", "bold cyan"),
                    ("Base: ", "dim"),
                    (f"{base_ref}\n", "bold white"),
                    ("Advisor: ", "dim"),
                    ("unavailable", "bold yellow"),
                ),
                title="Patch advisor gated",
                border_style="yellow",
            )
        )
        console.print(f"[yellow]No patch guidance was produced:[/yellow] {reason}")
        return

    review_prediction = advisor.get("review_prediction", {})
    expressed_feedback = (
        review_prediction.get("expressed_feedback", {})
        if isinstance(review_prediction, dict)
        else {}
    )
    summary = expressed_feedback.get("summary") or "Framework-backed patch guidance."
    console.print(
        Panel(
            RichText.assemble(
                ("Mini: ", "dim"),
                (f"{username}\n", "bold cyan"),
                ("Base: ", "dim"),
                (f"{base_ref}\n", "bold white"),
                ("Mode: ", "dim"),
                (str(advisor.get("mode") or "framework"), "bold white"),
            ),
            title="Patch advisor",
            border_style="blue",
        )
    )
    console.print(f"[bold]Summary:[/bold] {summary}")

    sections = [
        ("Change plan", "change_plan"),
        ("Do not change", "do_not_change"),
        ("Risks", "risks"),
        ("Expected reviewer objections", "expected_reviewer_objections"),
    ]
    for title, key in sections:
        items = advisor.get(key, []) or []
        if not isinstance(items, list) or not items:
            continue
        table = Table(title=title)
        table.add_column("Key", style="cyan")
        table.add_column("Confidence", justify="right")
        table.add_column("Summary")
        table.add_column("Framework")
        for item in items[:8]:
            if not isinstance(item, dict):
                continue
            confidence = item.get("confidence")
            confidence_str = (
                f"{float(confidence):.0%}" if isinstance(confidence, int | float) else "-"
            )
            table.add_row(
                str(item.get("key") or "unknown"),
                confidence_str,
                str(item.get("summary") or ""),
                str(item.get("framework_id") or ""),
            )
        console.print(table)

    evidence_refs = advisor.get("evidence_references", []) or []
    if isinstance(evidence_refs, list) and evidence_refs:
        console.print("[bold]Evidence references:[/bold]")
        for ref in evidence_refs[:5]:
            if not isinstance(ref, dict):
                continue
            evidence_ids = ", ".join(str(item) for item in ref.get("evidence_ids", [])[:3])
            console.print(
                f"- {ref.get('framework_id')}: {evidence_ids or 'no evidence ids'}"
            )


@app.command("list")
def list_minis():
    """List all minis in a table."""
    try:
        resp = httpx.get(f"{API_BASE}/minis", timeout=10)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]API error: {e.response.status_code}[/red]")
        raise typer.Exit(1)

    minis = resp.json()
    if not minis:
        console.print("[dim]No minis found.[/dim]")
        return

    table = Table(title="Minis")
    table.add_column("ID", style="dim")
    table.add_column("Username", style="cyan bold")
    table.add_column("Display Name")
    table.add_column("Status")
    table.add_column("Created")

    for m in minis:
        status = m["status"]
        if status == "ready":
            status_str = "[green]ready[/green]"
        elif status == "processing":
            status_str = "[yellow]processing[/yellow]"
        elif status == "failed":
            status_str = "[red]failed[/red]"
        else:
            status_str = status

        created = m.get("created_at", "")[:19].replace("T", " ")
        table.add_row(
            str(m["id"]),
            m["username"],
            m.get("display_name") or "",
            status_str,
            created,
        )

    console.print(table)


@app.command("get")
def get_mini(username: str):
    """Show mini details as pretty JSON."""
    try:
        resp = httpx.get(f"{API_BASE}/minis/by-username/{username}", timeout=10)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]Mini '{username}' not found.[/red]")
        else:
            console.print(f"[red]API error: {e.response.status_code}[/red]")
        raise typer.Exit(1)

    data = resp.json()
    console.print(JSON(json.dumps(data, indent=2, default=str)))


@app.command("create")
def create_mini(
    username: str,
    sources: list[str] = typer.Option(
        ["github", "claude_code"], "--source", "-s", help="Ingestion sources to use"
    ),
):
    """Create a mini via the API and poll until ready."""
    try:
        resp = httpx.post(
            f"{API_BASE}/minis",
            json={"username": username, "sources": sources},
            headers=_auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]API error: {e.response.status_code} — {e.response.text}[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Creating mini for '{username}'...[/yellow]")

    # Poll until ready or failed
    while True:
        time.sleep(3)
        try:
            poll = httpx.get(f"{API_BASE}/minis/by-username/{username}", timeout=10)
            poll.raise_for_status()
        except httpx.HTTPError:
            console.print(".", end="")
            continue

        data = poll.json()
        status = data.get("status", "unknown")

        if status == "ready":
            console.print(f"\n[green]Mini '{username}' is ready![/green]")
            console.print(f"  Display name: {data.get('display_name', 'N/A')}")
            console.print(f"  Bio: {(data.get('bio') or 'N/A')[:100]}")
            return
        elif status == "failed":
            console.print(f"\n[red]Mini '{username}' failed to create.[/red]")
            raise typer.Exit(1)
        else:
            console.print(".", end="", style="dim")
            sys.stdout.flush()


@app.command("pre-review")
def pre_review(
    username: str,
    base: str | None = typer.Option(
        None,
        "--base",
        help="Git ref to compare your current work against. Defaults to origin HEAD/main/master.",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Optional title override sent to the review-prediction backend.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional description override sent to the review-prediction backend.",
    ),
    author_model: ReviewAuthorModel = typer.Option(
        ReviewAuthorModel.unknown,
        "--author-model",
        help="How the mini should model your relationship to the author.",
    ),
    context: ReviewDeliveryContext = typer.Option(
        ReviewDeliveryContext.normal,
        "--context",
        help="Delivery context for the predicted review.",
    ),
):
    """Ask what a mini would likely block on before you request review."""
    try:
        resolved_base, request = _collect_pre_review_request(
            base_ref=base,
            title=title,
            description=description,
            author_model=author_model,
            delivery_context=context,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    headers = _auth_headers()

    try:
        mini_response = httpx.get(
            f"{API_BASE}/minis/by-username/{username}",
            headers=headers,
            timeout=10,
        )
        mini_response.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            console.print(f"[red]Mini '{username}' not found.[/red]")
        else:
            console.print(f"[red]API error: {exc.response.status_code}[/red]")
        raise typer.Exit(1)

    mini = mini_response.json()
    if mini.get("status") != "ready":
        console.print(f"[red]Mini '{username}' is not ready (status: {mini.get('status')}).[/red]")
        raise typer.Exit(1)

    try:
        prediction_response = httpx.post(
            f"{API_BASE}/minis/{mini['id']}/review-prediction",
            json=request,
            headers=headers,
            timeout=30,
        )
        prediction_response.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]API error: {exc.response.status_code} — {exc.response.text}[/red]")
        raise typer.Exit(1)

    _render_pre_review_report(username, resolved_base, prediction_response.json())


@app.command("patch-advisor")
def patch_advisor(
    username: str,
    base: str | None = typer.Option(
        None,
        "--base",
        help="Git ref to compare your current work against. Defaults to origin HEAD/main/master.",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Optional title override sent to the patch-advisor backend.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional description override sent to the patch-advisor backend.",
    ),
    author_model: ReviewAuthorModel = typer.Option(
        ReviewAuthorModel.unknown,
        "--author-model",
        help="How the mini should model your relationship to the author.",
    ),
    context: ReviewDeliveryContext = typer.Option(
        ReviewDeliveryContext.normal,
        "--context",
        help="Delivery context for the patch guidance.",
    ),
):
    """Ask a mini for framework-backed patch guidance for your local diff."""
    try:
        resolved_base, request = _collect_pre_review_request(
            base_ref=base,
            title=title,
            description=description,
            author_model=author_model,
            delivery_context=context,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    headers = _auth_headers()

    try:
        mini_response = httpx.get(
            f"{API_BASE}/minis/by-username/{username}",
            headers=headers,
            timeout=10,
        )
        mini_response.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            console.print(f"[red]Mini '{username}' not found.[/red]")
        else:
            console.print(f"[red]API error: {exc.response.status_code}[/red]")
        raise typer.Exit(1)

    mini = mini_response.json()
    if mini.get("status") != "ready":
        console.print(f"[red]Mini '{username}' is not ready (status: {mini.get('status')}).[/red]")
        raise typer.Exit(1)

    try:
        advisor_response = httpx.post(
            f"{API_BASE}/minis/{mini['id']}/patch-advisor",
            json=request,
            headers=headers,
            timeout=30,
        )
        advisor_response.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]API error: {exc.response.status_code} — {exc.response.text}[/red]")
        raise typer.Exit(1)

    _render_patch_advisor_report(username, resolved_base, advisor_response.json())


def _precision_recall_f1(
    expected_ids: set[str],
    predicted_ids: set[str],
) -> tuple[float, float, float]:
    """Compute strict agreement metrics."""
    if not expected_ids and not predicted_ids:
        return 1.0, 1.0, 1.0
    if not expected_ids or not predicted_ids:
        # If expected is empty but predicted is not: Precision=0, Recall=1, F1=0
        # If expected is not empty but predicted is: Precision=1, Recall=0, F1=0
        if not expected_ids:
            return 0.0, 1.0, 0.0
        else:
            return 1.0, 0.0, 0.0

    true_positives = len(expected_ids & predicted_ids)
    precision = true_positives / len(predicted_ids)
    recall = true_positives / len(expected_ids)
    f1 = 0.0
    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _calculate_metrics(cycles: list[ReviewCycle]) -> dict[str, float]:
    if not cycles:
        return {}

    total = len(cycles)
    approval_matches = 0
    blocker_precisions = []
    blocker_recalls = []
    comment_f1s = []

    for cycle in cycles:
        pred = cycle.predicted_state or {}
        human = cycle.human_review_outcome or {}

        # 1. Approval State Accuracy
        pred_verdict = pred.get("expressed_feedback", {}).get("approval_state")
        human_verdict = human.get("expressed_feedback", {}).get("approval_state")
        if pred_verdict == human_verdict:
            approval_matches += 1

        # 2. Blocker Precision/Recall
        pred_blockers = pred.get("private_assessment", {}).get("blocking_issues", [])
        human_blockers = human.get("private_assessment", {}).get("blocking_issues", [])

        def _to_set(items):
            return set(
                str(i.get("id") if isinstance(i, dict) else i).lower().strip() for i in items
            )

        p_set = _to_set(pred_blockers)
        h_set = _to_set(human_blockers)

        prec, rec, _ = _precision_recall_f1(h_set, p_set)
        blocker_precisions.append(prec)
        blocker_recalls.append(rec)

        # 3. Comment F1
        pred_comments = pred.get("expressed_feedback", {}).get("comments", [])
        human_comments = human.get("expressed_feedback", {}).get("comments", [])

        def _to_comm_set(items):
            return set(
                str(i.get("body") if isinstance(i, dict) else i).lower().strip() for i in items
            )

        p_comm_set = _to_comm_set(pred_comments)
        h_comm_set = _to_comm_set(human_comments)
        _, _, f1 = _precision_recall_f1(h_comm_set, p_comm_set)
        comment_f1s.append(f1)

    return {
        "count": float(total),
        "approval_accuracy": approval_matches / total,
        "blocker_precision": sum(blocker_precisions) / len(blocker_precisions),
        "blocker_recall": sum(blocker_recalls) / len(blocker_recalls),
        "comment_f1": sum(comment_f1s) / len(comment_f1s),
    }


@app.command("agreement")
def show_agreement(username: str):
    """Show Moat Proof agreement metrics for a mini."""

    async def _run():
        async with async_session() as session:
            # Get mini
            stmt = select(Mini).where(Mini.username == username.lower())
            result = await session.execute(stmt)
            mini = result.scalar_one_or_none()

            if not mini:
                console.print(f"[red]Mini '{username}' not found.[/red]")
                raise typer.Exit(1)

            # Get cycles with human outcome
            cycle_stmt = (
                select(ReviewCycle)
                .where(ReviewCycle.mini_id == mini.id)
                .where(ReviewCycle.human_review_outcome.isnot(None))
                .order_by(ReviewCycle.predicted_at.asc())
            )
            cycle_result = await session.execute(cycle_stmt)
            cycles = list(cycle_result.scalars().all())

            if not cycles:
                console.print(
                    f"[yellow]No review cycles with human outcomes found for {username}.[/yellow]"
                )
                return

            total_metrics = _calculate_metrics(cycles)

            # Trend calculation: split in two halves
            n = len(cycles)
            if n >= 2:
                mid = n // 2
                first_half = _calculate_metrics(cycles[:mid])
                recent_half = _calculate_metrics(cycles[mid:])
            else:
                first_half = None
                recent_half = None

            table = Table(
                title=f"Moat Proof: {mini.username}", show_header=True, header_style="bold magenta"
            )
            table.add_column("Metric", style="cyan")
            table.add_column("Score", justify="right")
            table.add_column("Trend", justify="center")

            def format_score(val: float) -> str:
                return f"{val:.1%}"

            def get_trend(metric_key: str) -> str:
                if not first_half or not recent_half:
                    return "[dim]—[/dim]"

                diff = recent_half[metric_key] - first_half[metric_key]
                if abs(diff) < 0.001:
                    return "[dim]→[/dim]"
                elif diff > 0:
                    return f"[green]↑ +{diff:.1%}[/green]"
                else:
                    return f"[red]↓ {diff:.1%}[/red]"

            metrics_to_show = [
                ("Approval Accuracy", "approval_accuracy"),
                ("Blocker Precision", "blocker_precision"),
                ("Blocker Recall", "blocker_recall"),
                ("Comment F1", "comment_f1"),
            ]

            for label, key in metrics_to_show:
                table.add_row(label, format_score(total_metrics[key]), get_trend(key))

            console.print(
                Panel(
                    RichText.assemble(
                        ("Mini: ", "dim"),
                        (f"{mini.username}\n", "bold cyan"),
                        ("Cycles: ", "dim"),
                        (f"{len(cycles)}", "bold white"),
                    ),
                    title="Mini Agreement Dashboard",
                    border_style="blue",
                )
            )
            console.print(table)

    import asyncio

    try:
        asyncio.run(_run())
    except Exception as e:
        console.print(f"[red]Error fetching metrics: {e}[/red]")
        raise typer.Exit(1)


@app.command("delete")
def delete_mini(username: str):
    """Delete a mini directly from the SQLite database."""
    if not os.path.exists(DB_PATH):
        console.print("[red]Database file not found.[/red]")
        raise typer.Exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM minis WHERE username = ?", (username.lower(),))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted:
        console.print(f"[green]Deleted mini '{username}'.[/green]")
    else:
        console.print(f"[yellow]Mini '{username}' not found in database.[/yellow]")


@app.command("recreate")
def recreate_mini(
    username: str,
    sources: list[str] = typer.Option(
        ["github", "claude_code"], "--source", "-s", help="Ingestion sources to use"
    ),
):
    """Delete and recreate a mini."""
    delete_mini(username)
    create_mini(username, sources=sources)


@app.command("chat")
def chat_with_mini(username: str):
    """Interactive terminal chat with a mini via SSE streaming."""
    # Verify mini exists and is ready
    try:
        resp = httpx.get(f"{API_BASE}/minis/by-username/{username}", timeout=10)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]Mini '{username}' not found.[/red]")
        else:
            console.print(f"[red]API error: {e.response.status_code}[/red]")
        raise typer.Exit(1)

    data = resp.json()
    if data.get("status") != "ready":
        console.print(f"[red]Mini '{username}' is not ready (status: {data.get('status')}).[/red]")
        raise typer.Exit(1)

    mini_id = data["id"]
    display = data.get("display_name") or username
    console.print(f"[bold cyan]Chatting with {display}[/bold cyan]")
    console.print("[dim]Type 'quit' or 'exit' to end the conversation.[/dim]\n")

    history: list[dict[str, str]] = []

    while True:
        try:
            message = console.input("[bold green]You:[/bold green] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if message.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if not message.strip():
            continue

        console.print(f"[bold cyan]{display}:[/bold cyan] ", end="")

        assistant_response = ""
        try:
            with httpx.stream(
                "POST",
                f"{API_BASE}/minis/{mini_id}/chat",
                json={"message": message, "history": history},
                timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
            ) as stream:
                for line in stream.iter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        # The SSE events: "token" has text chunks, "done"/"error" are terminal
                        print(chunk, end="", flush=True)
                        assistant_response += chunk
                    elif line.startswith("event: "):
                        event_type = line[7:].strip()
                        if event_type == "done":
                            break
                        elif event_type == "error":
                            break
        except httpx.ReadTimeout:
            console.print("\n[red]Response timed out.[/red]")
            continue
        except httpx.ConnectError:
            console.print("\n[red]Lost connection to API.[/red]")
            break

        print()  # newline after streamed response

        # Append to history for multi-turn
        history.append({"role": "user", "content": message})
        if assistant_response:
            history.append({"role": "assistant", "content": assistant_response})


_FW_HIGH_CONF = 0.7
_FW_LOW_CONF = 0.3


def _confidence_badge(confidence: float, revision: int) -> str:
    """Return display badges for a decision framework based on confidence and revision."""
    parts: list[str] = []
    if confidence > _FW_HIGH_CONF:
        parts.append("[HIGH CONFIDENCE ✓]")
    elif confidence < _FW_LOW_CONF:
        parts.append("[LOW CONFIDENCE ⚠]")
    if revision > 0:
        parts.append(f"[validated {revision} time{'s' if revision != 1 else ''}]")
    return " ".join(parts)


@app.command("decision-frameworks")
def show_decision_frameworks(
    username: str,
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="Minimum confidence threshold (0–1)."),
    limit: int = typer.Option(20, "--limit", help="Maximum number of frameworks to display."),
):
    """Show a mini's decision-framework profile from the database.

    Useful for spot-checking confidence and revision counts after a review-cycle
    outcome lands without needing a running API server.
    """

    async def _run() -> None:
        async with async_session() as session:
            stmt = select(Mini).where(Mini.username == username.lower())
            result = await session.execute(stmt)
            mini = result.scalar_one_or_none()

            if not mini:
                console.print(f"[red]Mini '{username}' not found.[/red]")
                raise typer.Exit(1)

            principles = mini.principles_json or {}
            df_payload = principles if isinstance(principles, dict) else {}
            raw_frameworks = df_payload.get("decision_frameworks") or df_payload.get("frameworks") or []

            # Also check top-level if the column holds DecisionFrameworkProfile directly
            if not raw_frameworks and isinstance(principles, dict):
                raw_frameworks = principles.get("frameworks") or []

            if not raw_frameworks:
                console.print(
                    f"[yellow]No decision frameworks found for '{username}'. "
                    "Run the synthesis pipeline first.[/yellow]"
                )
                raise typer.Exit(1)

            # Parse, filter, sort, limit
            parsed: list[dict] = []
            for raw in raw_frameworks:
                if not isinstance(raw, dict):
                    continue
                try:
                    conf = float(raw.get("confidence", 0.5))
                except (TypeError, ValueError):
                    conf = 0.5
                try:
                    rev = int(raw.get("revision", 0))
                except (TypeError, ValueError):
                    rev = 0
                parsed.append({
                    "framework_id": raw.get("framework_id") or raw.get("id") or "—",
                    "condition": raw.get("condition") or raw.get("trigger") or "",
                    "action": (raw.get("decision_order") or [""])[0]
                        if isinstance(raw.get("decision_order"), list)
                        else (raw.get("action") or ""),
                    "value": (raw.get("value_ids") or [""])[0].replace("value:", "").replace("_", " ")
                        if isinstance(raw.get("value_ids"), list) and raw.get("value_ids")
                        else (raw.get("value") or raw.get("tradeoff") or ""),
                    "confidence": conf,
                    "revision": rev,
                })

            filtered = [fw for fw in parsed if fw["confidence"] >= min_confidence]
            filtered.sort(key=lambda fw: (-fw["confidence"], -fw["revision"]))
            filtered = filtered[:limit]

            if not filtered:
                console.print(
                    f"[yellow]No frameworks meet min-confidence={min_confidence:.2f} for '{username}'.[/yellow]"
                )
                raise typer.Exit(1)

            # Render
            table = Table(
                title=f"Decision Frameworks — {mini.username}",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Framework", style="cyan", no_wrap=False, max_width=24)
            table.add_column("Trigger → Action → Value", no_wrap=False, max_width=52)
            table.add_column("Confidence", justify="right")
            table.add_column("Rev", justify="right")
            table.add_column("Badges", no_wrap=False)

            for fw in filtered:
                action = fw["action"]
                value = fw["value"]
                if action and value:
                    tav = f"{fw['condition']} → {action} → {value}"
                elif action:
                    tav = f"{fw['condition']} → {action}"
                elif value:
                    tav = f"{fw['condition']} → {value}"
                else:
                    tav = fw["condition"] or "—"

                conf = fw["confidence"]
                rev = fw["revision"]
                conf_color = "green" if conf > _FW_HIGH_CONF else ("red" if conf < _FW_LOW_CONF else "yellow")
                badge_str = _confidence_badge(conf, rev)

                table.add_row(
                    fw["framework_id"],
                    tav,
                    f"[{conf_color}]{conf:.0%}[/{conf_color}]",
                    str(rev),
                    badge_str or "[dim]—[/dim]",
                )

            mean_conf = sum(fw["confidence"] for fw in filtered) / len(filtered)
            max_rev = max(fw["revision"] for fw in filtered)

            console.print(
                Panel(
                    RichText.assemble(
                        ("Mini: ", "dim"),
                        (f"{mini.username}\n", "bold cyan"),
                        ("Showing: ", "dim"),
                        (f"{len(filtered)}", "bold white"),
                        (" / ", "dim"),
                        (f"{len(parsed)} frameworks", "white"),
                        ("  |  mean confidence: ", "dim"),
                        (f"{mean_conf:.0%}", "bold white"),
                        ("  |  max revision: ", "dim"),
                        (f"{max_rev}", "bold white"),
                    ),
                    title="Decision Framework Profile",
                    border_style="blue",
                )
            )
            console.print(table)

    import asyncio

    try:
        asyncio.run(_run())
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error fetching frameworks: {e}[/red]")
        raise typer.Exit(1)


@db_app.command("reset")
def db_reset():
    """Delete the SQLite database file."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        console.print("[green]Database deleted.[/green]")
    else:
        console.print("[yellow]Database file not found (already clean).[/yellow]")


if __name__ == "__main__":
    app()
