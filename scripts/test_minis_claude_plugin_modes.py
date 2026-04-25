from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().with_name("minis_claude_plugin_modes.py")


def _load_script():
    spec = importlib.util.spec_from_file_location("minis_claude_plugin_modes_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class MinisClaudePluginModesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_script()

    def test_local_demo_dry_run_collects_repo_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init")
            _git(repo, "config", "user.name", "Demo Dev")
            _git(repo, "config", "user.email", "demo@example.com")
            (repo / "README.md").write_text("# Demo Repo\n\n## Decisions\n", encoding="utf-8")
            _git(repo, "add", "README.md")
            _git(repo, "commit", "-m", "MINI-98 seed local demo context")

            previous_cwd = Path.cwd()
            try:
                os.chdir(repo)
                result = self.module.main(["local-demo", "--dry-run"])
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(result, 0)

    def test_local_demo_writes_agent_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init")
            _git(repo, "config", "user.name", "Demo Dev")
            _git(repo, "config", "user.email", "demo@example.com")
            (repo / "README.md").write_text("# Demo Repo\n", encoding="utf-8")
            _git(repo, "add", "README.md")
            _git(repo, "commit", "-m", "MINI-109 seed remote mode notes")

            previous_cwd = Path.cwd()
            try:
                os.chdir(repo)
                result = self.module.main(["local-demo"])
            finally:
                os.chdir(previous_cwd)

            agent_path = repo / ".claude" / "agents" / "demo-dev-local-mini.md"
            evidence_path = repo / ".claude" / "minis" / "demo-dev-local-mini.evidence.json"
            self.assertEqual(result, 0)
            self.assertTrue(agent_path.exists())
            self.assertTrue(evidence_path.exists())
            agent_content = agent_path.read_text(encoding="utf-8")
            self.assertIn("remote account mode is", agent_content)
            self.assertIn("required", agent_content)

    def test_remote_check_gates_when_token_missing(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            completed = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "remote-check", "--json"],
                check=False,
                capture_output=True,
                text=True,
                env={"PATH": os.environ.get("PATH", ""), "HOME": home},
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn('"available": false', completed.stdout)
        self.assertIn("MINIS_TOKEN", completed.stdout)

    def test_remote_setup_accepts_mcp_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "mcp-token"
            token_file.write_text("token-from-device-auth\n", encoding="utf-8")
            payload = self.module._remote_setup_payload({"MINIS_AUTH_TOKEN_FILE": str(token_file)})

        self.assertTrue(payload["available"])
        self.assertEqual(payload["auth_source"], str(token_file))


if __name__ == "__main__":
    unittest.main()
