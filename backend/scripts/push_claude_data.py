#!/usr/bin/env python3
"""Push Claude Code conversation data to the Minis API.

Usage:
    python scripts/push_claude_data.py --api-url http://localhost:8000 --token <jwt>
"""

import argparse
import io
import sys
import zipfile
from pathlib import Path

import httpx


def discover_jsonl_files(root: Path) -> list[Path]:
    """Find all JSONL files under ~/.claude/projects/."""
    files = []
    if not root.exists():
        return files
    for jsonl in root.rglob("*.jsonl"):
        files.append(jsonl)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="Push Claude Code data to Minis API")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Minis API base URL")
    parser.add_argument("--token", required=True, help="JWT auth token")
    parser.add_argument("--path", default="~/.claude/projects", help="Path to Claude Code projects")
    args = parser.parse_args()

    root = Path(args.path).expanduser()
    files = discover_jsonl_files(root)

    if not files:
        print(f"No JSONL files found in {root}")
        sys.exit(1)

    print(f"Found {len(files)} JSONL file(s)")

    # Create zip in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arcname = f.relative_to(root).as_posix().replace("/", "__")
            if not arcname.endswith(".jsonl"):
                arcname += ".jsonl"
            zf.write(f, arcname)
    buf.seek(0)

    total_size = buf.getbuffer().nbytes
    print(f"Packaged into {total_size / 1024:.1f} KB zip")

    # Upload
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            f"{args.api_url}/api/upload/claude-code",
            headers={"Authorization": f"Bearer {args.token}"},
            files={"files": ("claude_code.zip", buf, "application/zip")},
        )

    if resp.status_code == 200:
        data = resp.json()
        print(f"Success! Saved {data['files_saved']} file(s), {data['total_size']} bytes")
    else:
        print(f"Error {resp.status_code}: {resp.text}")
        sys.exit(1)


if __name__ == "__main__":
    main()
