#!/usr/bin/env python3
"""Seed the Minis backend with demo profiles.

Usage:
    python scripts/seed_demo.py                         # defaults to http://localhost:8000
    python scripts/seed_demo.py --api-url https://...   # custom backend URL
"""

from __future__ import annotations

import argparse
import sys
import time

import urllib.request
import urllib.error
import json

DEMO_USERNAMES = [
    "alliecatowo",
    "torvalds",
    "gaearon",
    "mitchellh",
    "theniceboy",
]

POLL_INTERVAL = 5  # seconds
TIMEOUT = 300  # max seconds per mini


def create_mini(api_url: str, username: str) -> dict:
    data = json.dumps({"username": username, "sources": ["github"]}).encode()
    req = urllib.request.Request(
        f"{api_url}/api/minis",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_mini(api_url: str, username: str) -> dict:
    req = urllib.request.Request(f"{api_url}/api/minis/{username}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def wait_for_ready(api_url: str, username: str) -> str:
    start = time.time()
    while time.time() - start < TIMEOUT:
        mini = get_mini(api_url, username)
        status = mini.get("status", "unknown")
        if status == "ready":
            return "ready"
        if status == "failed":
            return "failed"
        print(f"  [{username}] status: {status} ... waiting")
        time.sleep(POLL_INTERVAL)
    return "timeout"


def main():
    parser = argparse.ArgumentParser(description="Seed demo minis")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Backend API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for pipelines to complete",
    )
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")

    # Health check
    try:
        req = urllib.request.Request(f"{api_url}/api/health")
        with urllib.request.urlopen(req) as resp:
            health = json.loads(resp.read())
            print(f"Backend healthy: {health}")
    except Exception as e:
        print(f"ERROR: Cannot reach backend at {api_url}/api/health: {e}")
        sys.exit(1)

    results = {}
    for username in DEMO_USERNAMES:
        print(f"\nCreating mini for '{username}' ...")
        try:
            result = create_mini(api_url, username)
            print(f"  Created: status={result.get('status')}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  HTTP {e.code}: {body}")
            results[username] = f"error ({e.code})"
            continue

        if args.no_wait:
            results[username] = result.get("status", "unknown")
        else:
            print(f"  Waiting for pipeline to complete ...")
            final = wait_for_ready(api_url, username)
            results[username] = final
            print(f"  Final status: {final}")

    print("\n=== Demo Seed Results ===")
    for username, status in results.items():
        marker = "[OK]" if status == "ready" else "[!!]"
        print(f"  {marker} {username}: {status}")


if __name__ == "__main__":
    main()
