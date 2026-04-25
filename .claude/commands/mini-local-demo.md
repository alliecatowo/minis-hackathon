---
allowed-tools: Bash(python:*), Bash(git status:*), Bash(git log:*), Bash(ls:*)
description: Generate a local demo mini from this repository without hosted Minis. Usage: /mini-local-demo [display_name]
---

## Your Task

The user wants a local/demo-mode mini generated from the current repository. The arguments provided are: $ARGUMENTS

Follow these steps exactly:

1. Parse the optional display name from `$ARGUMENTS`. If omitted, let the helper use the local git user name.

2. Generate the local demo mini:

   ```bash
   python scripts/minis_claude_plugin_modes.py local-demo --force --name "<display_name>"
   ```

   If no display name was provided, omit `--name`.

3. Report the generated `agent` and `evidence` paths from the JSON output.

4. Tell the user the mini is available as the `usage` handle shown by the helper.

5. Make the boundary explicit: this local demo mini is grounded only in local git metadata and allowlisted repository docs. It does not use hosted account evidence, private Minis evidence, or a backend. If the user asks for hosted/account data, direct them to `/mini-remote-account`.
