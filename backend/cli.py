"""Minis CLI — dev convenience tool for managing minis locally."""

import json
import os
import sqlite3
import sys
import time

import httpx
import typer
from rich.console import Console
from rich.json import JSON
from rich.table import Table

API_BASE = "http://localhost:8000/api"
DB_PATH = os.path.join(os.getcwd(), "minis.db")

app = typer.Typer(help="Minis CLI — manage your developer personality clones.")
db_app = typer.Typer(help="Database operations.")
app.add_typer(db_app, name="db")

console = Console()


def _auth_headers() -> dict[str, str]:
    """Get auth headers from MINIS_TOKEN env var."""
    token = os.environ.get("MINIS_TOKEN", "")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


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
    sources: list[str] = typer.Option(["github"], "--source", "-s", help="Ingestion sources to use"),
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
    sources: list[str] = typer.Option(["github"], "--source", "-s", help="Ingestion sources to use"),
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
