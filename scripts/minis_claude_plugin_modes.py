#!/usr/bin/env python3
"""Runnable Claude Code plugin mode helpers for Minis.

The script intentionally has no third-party dependencies. Local/demo mode only
reads a small allowlist of repository metadata and docs. Remote account mode is
explicitly gated on API auth and never falls back to public/anonymous behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API_BASE = "https://minis-api.fly.dev/api"
DOC_ALLOWLIST = (
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "docs/PROGRAM.md",
    "docs/REVIEW_INTELLIGENCE.md",
)


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _repo_root(cwd: Path) -> Path:
    root = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if not root:
        raise SystemExit("local-demo must be run inside a git repository")
    return Path(root)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "local"


def _api_base(env: dict[str, str]) -> str:
    raw = (
        env.get("MINIS_API_BASE")
        or env.get("MINIS_BACKEND_API")
        or env.get("MINIS_BACKEND_URL")
        or DEFAULT_API_BASE
    ).strip()
    raw = raw.rstrip("/")
    if raw.endswith("/api"):
        return raw
    return f"{raw}/api"


def _auth_token(env: dict[str, str]) -> str:
    return (env.get("MINIS_TOKEN") or env.get("MINIS_AUTH_TOKEN") or "").strip()


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _read_doc_headings(root: Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for rel_path in DOC_ALLOWLIST:
        path = root / rel_path
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        headings = [
            line.strip()
            for line in lines
            if line.startswith("#") and len(line.strip("# ").strip()) > 0
        ][:12]
        if headings:
            docs.append({"path": rel_path, "headings": "\n".join(headings)})
    return docs


def _collect_local_context(root: Path, requested_name: str | None) -> dict[str, Any]:
    author_name = requested_name or _run_git(["config", "user.name"], root) or "Local Developer"
    author_email = _run_git(["config", "user.email"], root) or ""
    branch = _run_git(["branch", "--show-current"], root) or "detached"
    remote = _run_git(["remote", "get-url", "origin"], root) or ""
    repo_name = root.name

    log_args = ["log", "-n", "12", "--date=short", "--pretty=format:%h\t%ad\t%s"]
    if author_email:
        log_args.insert(3, f"--author={author_email}")
    commits_raw = _run_git(log_args, root) or ""
    commits = []
    for line in commits_raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})

    diff_stat = _run_git(["diff", "--stat", "HEAD"], root) or ""
    changed_files = (_run_git(["diff", "--name-only", "HEAD"], root) or "").splitlines()

    return {
        "mode": "local-demo",
        "repo": {"name": repo_name, "root": str(root), "branch": branch, "remote": remote},
        "subject": {"name": author_name, "email": author_email},
        "evidence": {
            "recent_commits": commits,
            "working_tree_changed_files": changed_files,
            "working_tree_diff_stat": diff_stat,
            "doc_headings": _read_doc_headings(root),
        },
        "limits": [
            "Generated only from local git metadata and allowlisted repository docs.",
            "Does not call the hosted Minis backend or any LLM service.",
            "Must say unavailable when asked for evidence outside the local context.",
        ],
    }


def _render_local_agent(context: dict[str, Any]) -> str:
    subject = context["subject"]
    repo = context["repo"]
    evidence = context["evidence"]
    agent_name = f"{_slug(subject['name'])}-local-mini"
    commits = evidence.get("recent_commits", [])[:8]
    commit_lines = "\n".join(
        f"- {commit['date']} {commit['sha']}: {commit['subject']}" for commit in commits
    ) or "- No authored commits were found in this repository."
    changed_files = "\n".join(f"- {path}" for path in evidence.get("working_tree_changed_files", []))
    if not changed_files:
        changed_files = "- No current working-tree changes."
    doc_lines = []
    for doc in evidence.get("doc_headings", []):
        compact_headings = "; ".join(doc["headings"].splitlines()[:6])
        doc_lines.append(f"- {doc['path']}: {compact_headings}")
    docs = "\n".join(doc_lines) or "- No allowlisted docs with headings were found."

    return textwrap.dedent(
        f"""\
        ---
        name: {agent_name}
        description: Local demo mini for {subject['name']} generated from this repository's local context.
        model: inherit
        ---

        You are a local-demo Minis agent for {subject['name']}.

        This is not a hosted Minis account mini. You are grounded only in the
        local evidence bundled below from repository `{repo['name']}` on branch
        `{repo['branch']}`. Do not pretend to know private account evidence,
        hosted profile data, or review history that is not listed here.

        ## Operating Contract

        - Use the local evidence to answer as a pragmatic coding partner.
        - When asked for a real decision-framework clone, account minis, private
          evidence, or hosted conversations, say that remote account mode is
          required.
        - When evidence is absent, say what is unavailable instead of inventing
          a fallback.
        - For reviews, focus on likely local project norms, changed files, and
          concrete risk. Avoid generic lint-bot feedback.

        ## Local Evidence

        Subject: {subject['name']} <{subject['email'] or 'unknown email'}>
        Repository: {repo['name']}
        Remote: {repo['remote'] or 'none'}

        Recent authored commits:
        {commit_lines}

        Current changed files:
        {changed_files}

        Allowlisted repository docs:
        {docs}

        ## Usage

        Mention this agent in Claude Code as `@{agent_name}` for local demo
        conversations and pre-review advice. For hosted/account minis, use
        `/mini-remote-account` or the Minis MCP server instead.
        """
    )


def _write_text(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"{path} already exists; pass --force to overwrite generated output")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _local_demo(args: argparse.Namespace) -> int:
    root = _repo_root(Path.cwd())
    context = _collect_local_context(root, args.name)
    agent_name = f"{_slug(context['subject']['name'])}-local-mini"
    agent_markdown = _render_local_agent(context)

    if args.dry_run:
        print(
            _json_dump(
                {
                    "status": "ready",
                    "agent_name": agent_name,
                    "repo": context["repo"],
                    "subject": context["subject"],
                    "evidence_counts": {
                        "recent_commits": len(context["evidence"]["recent_commits"]),
                        "changed_files": len(context["evidence"]["working_tree_changed_files"]),
                        "doc_headings": len(context["evidence"]["doc_headings"]),
                    },
                }
            )
        )
        return 0

    output_dir = (root / args.output_dir).resolve()
    evidence_dir = (root / args.evidence_dir).resolve()
    agent_path = output_dir / f"{agent_name}.md"
    evidence_path = evidence_dir / f"{agent_name}.evidence.json"
    _write_text(agent_path, agent_markdown, force=args.force)
    _write_text(evidence_path, _json_dump(context) + "\n", force=args.force)
    print(
        _json_dump(
            {
                "status": "ready",
                "agent": str(agent_path),
                "evidence": str(evidence_path),
                "usage": f"@{agent_name}",
            }
        )
    )
    return 0


def _remote_setup_payload(env: dict[str, str]) -> dict[str, Any]:
    api_base = _api_base(env)
    token_present = bool(_auth_token(env))
    return {
        "mode": "remote-account",
        "available": token_present,
        "api_base": api_base,
        "auth": "configured" if token_present else "missing",
        "setup": [
            "Set MINIS_TOKEN or MINIS_AUTH_TOKEN to a Minis API bearer token.",
            "Optionally set MINIS_API_BASE or MINIS_BACKEND_URL; defaults to https://minis-api.fly.dev/api.",
            "For MCP clients, pass MINIS_BACKEND_URL and MINIS_AUTH_TOKEN into the minis MCP server env.",
        ],
    }


def _remote_setup_text(payload: dict[str, Any]) -> str:
    if payload["available"]:
        return textwrap.dedent(
            f"""\
            Remote account mode is configured.
            API: {payload['api_base']}

            Claude Code MCP env:
              MINIS_BACKEND_URL={payload['api_base'].removesuffix('/api')}
              MINIS_AUTH_TOKEN=<configured>
            """
        ).strip()
    setup_lines = "\n".join(f"- {line}" for line in payload["setup"])
    return textwrap.dedent(
        f"""\
        Remote account mode is unavailable: missing API auth.
        API: {payload['api_base']}

        Setup:
        {setup_lines}
        """
    ).strip()


def _remote_check(args: argparse.Namespace) -> int:
    payload = _remote_setup_payload(os.environ)
    if not payload["available"]:
        print(_json_dump(payload) if args.json else _remote_setup_text(payload))
        return 2
    if args.probe:
        payload["probe"] = _request_json("/minis?mine=true", timeout=args.timeout_seconds)
    print(_json_dump(payload) if args.json else _remote_setup_text(payload))
    return 0


def _request_json(path: str, *, timeout: float) -> Any:
    token = _auth_token(os.environ)
    if not token:
        raise SystemExit("remote account API calls require MINIS_TOKEN or MINIS_AUTH_TOKEN")
    url = f"{_api_base(os.environ)}{path}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"remote account API call failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot connect to Minis API at {_api_base(os.environ)}: {exc}") from exc


def _remote_list(args: argparse.Namespace) -> int:
    payload = _remote_setup_payload(os.environ)
    if not payload["available"]:
        print(_json_dump(payload) if args.json else _remote_setup_text(payload))
        return 2
    print(_json_dump(_request_json("/minis?mine=true", timeout=args.timeout_seconds)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    local = subcommands.add_parser(
        "local-demo",
        help="Generate a local Claude Code demo mini from current repository context.",
    )
    local.add_argument("--name", help="Display name for the local mini subject.")
    local.add_argument("--output-dir", default=".claude/agents")
    local.add_argument("--evidence-dir", default=".claude/minis")
    local.add_argument("--force", action="store_true", help="Overwrite generated local demo files.")
    local.add_argument("--dry-run", action="store_true", help="Collect context but do not write files.")
    local.set_defaults(func=_local_demo)

    remote_check = subcommands.add_parser(
        "remote-check",
        help="Check whether hosted account mode has API/MCP auth configured.",
    )
    remote_check.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    remote_check.add_argument("--probe", action="store_true", help="Call /api/minis?mine=true.")
    remote_check.add_argument("--timeout-seconds", type=float, default=10.0)
    remote_check.set_defaults(func=_remote_check)

    remote_list = subcommands.add_parser(
        "remote-list",
        help="List minis from the authenticated hosted account.",
    )
    remote_list.add_argument("--json", action="store_true", help="Reserved for command symmetry.")
    remote_list.add_argument("--timeout-seconds", type=float, default=10.0)
    remote_list.set_defaults(func=_remote_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
