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


def _render_pre_review_report(username: str, base_ref: str, prediction: dict[str, object]) -> None:
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
        for blocker in blockers:
            confidence = blocker.get("confidence")
            confidence_str = (
                f"{float(confidence):.0%}" if isinstance(confidence, int | float) else "—"
            )
            table.add_row(
                str(blocker.get("key") or "unknown"),
                confidence_str,
                str(blocker.get("summary") or ""),
            )
        console.print(table)
    else:
        console.print("[green]No likely blockers surfaced by this mini.[/green]")

    if open_questions:
        console.print("[bold]Open questions:[/bold]")
        for question in open_questions[:5]:
            console.print(f"- {question.get('summary') or question.get('rationale') or 'Unknown question'}")


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


@app.command("decision-frameworks")
def show_decision_frameworks(
    username: str,
    limit: int = typer.Option(20, "--limit", "-l", help="Max frameworks to display"),
    min_confidence: float = typer.Option(
        0.0, "--min-confidence", "-c", help="Minimum confidence threshold (0.0-1.0)"
    ),
):
    """Show decision frameworks for a mini, sorted by confidence."""

    async def _run():
        async with async_session() as session:
            # Get mini
            stmt = select(Mini).where(Mini.username == username.lower())
            result = await session.execute(stmt)
            mini = result.scalar_one_or_none()

            if not mini:
                console.print(f"[red]Mini '{username}' not found.[/red]")
                raise typer.Exit(1)

            # Extract decision frameworks from principles_json
            frameworks = []
            if mini.principles_json and "decision_frameworks" in mini.principles_json:
                frameworks = mini.principles_json["decision_frameworks"].get("frameworks", [])

            if not frameworks:
                console.print(f"[yellow]No decision frameworks found for {username}.[/yellow]")
                return

            # Filter and sort by confidence (desc), then revision (desc)
            filtered = [
                fw for fw in frameworks if fw.get("confidence", 0) >= min_confidence
            ]
            filtered.sort(
                key=lambda x: (-x.get("confidence", 0), -x.get("revision", 0))
            )

            # Take limit
            filtered = filtered[:limit]

            if not filtered:
                console.print(
                    f"[yellow]No frameworks with confidence >= {min_confidence}.[/yellow]"
                )
                return

            # Build table
            table = Table(
                title=f"Decision Frameworks: {mini.username}",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Confidence", justify="right", style="cyan")
            table.add_column("Rev", justify="right", style="dim")
            table.add_column("Framework ID", style="dim")
            table.add_column("Trigger")
            table.add_column("Action")
            table.add_column("Value")

            for fw in filtered:
                conf = fw.get("confidence", 0)
                rev = fw.get("revision", 0)
                fw_id = str(fw.get("framework_id", ""))[:8]
                trigger = str(fw.get("trigger", ""))[:60]
                action = str(fw.get("action", ""))[:60]
                value = str(fw.get("value", ""))[:40]

                conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
                rev_str = str(rev) if isinstance(rev, int) else "—"

                table.add_row(conf_str, rev_str, fw_id, trigger, action, value)

            console.print(table)

            # Summary line
            mean_conf = sum(fw.get("confidence", 0) for fw in filtered) / len(filtered)
            max_rev = max((fw.get("revision", 0) for fw in filtered), default=0)
            console.print(
                f"\n[dim]{len(filtered)} frameworks, mean confidence {mean_conf:.2f}, "
                f"max revision {int(max_rev)}[/dim]"
            )

    import asyncio

    try:
        asyncio.run(_run())
    except Exception as e:
        console.print(f"[red]Error fetching frameworks: {e}[/red]")
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
