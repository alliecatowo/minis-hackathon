---
allowed-tools: Bash(curl:*), Bash(git diff:*), Bash(git status:*), Bash(git log:*)
description: Assemble a team of developer minis for collaborative review or discussion. Usage: /mini-team <action> [username1 username2 ...] where action is "review", "discuss", or "brainstorm"
---

## Context

- Git diff of current changes: !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Recent commits: !`git log --oneline -5`

## Your Task

The user wants to assemble a team of developer minis. The arguments provided are: $ARGUMENTS

**Follow these steps exactly:**

1. **Parse the arguments.** The first argument is the action (`review`, `discuss`, or `brainstorm`). Remaining arguments are GitHub usernames. If no arguments provided, show usage:
   > **Usage:** `/mini-team <action> [usernames...]`
   >
   > **Actions:**
   > - `review` - Collaborative code review from multiple perspectives
   > - `discuss` - Architecture or design discussion
   > - `brainstorm` - Creative brainstorming session
   >
   > **Example:** `/mini-team review torvalds dhh`

   If no usernames provided, list available minis:
   ```
   curl -s http://localhost:8000/api/minis | jq -r '.[] | select(.status == "ready") | "  - \(.username) (\(.display_name // .username))"'
   ```

2. **Fetch each mini's details.** For each username, run:
   ```
   curl -s http://localhost:8000/api/minis/<username>
   ```
   Collect the `display_name`, `system_prompt`, and `values_json` for each. Skip any that are not found (404) or not ready, and inform the user.

3. **Execute the team action.**

   ### For `review`:
   Get the current git diff. For each mini, send the diff for review:
   ```
   curl -s -N -X POST http://localhost:8000/api/minis/<username>/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Please review these code changes from your perspective. Focus on what matters most to you based on your values and experience. Be concise but specific.\n\n```diff\n<DIFF>\n```", "history": []}'
   ```
   Collect each response and present them sequentially:
   ```
   ## Team Code Review

   ### @<username1> (<display_name1>)
   <review>

   ---

   ### @<username2> (<display_name2>)
   <review>

   ---

   ### Summary
   <synthesize key themes across all reviews>
   ```

   ### For `discuss`:
   Ask the user for a topic or question. Then for each mini, get their perspective:
   ```
   {"message": "Share your perspective on this topic: <TOPIC>. Draw on your experience and values.", "history": []}
   ```
   Present each perspective, then synthesize areas of agreement and disagreement.

   ### For `brainstorm`:
   Ask the user for the problem or idea to brainstorm. Then for each mini, get ideas:
   ```
   {"message": "Brainstorm ideas and approaches for: <PROBLEM>. Think creatively based on your experience.", "history": []}
   ```
   Present each mini's ideas, then synthesize the most promising approaches.

4. **Present the team output.** Always end with a synthesis section that identifies:
   - Common themes across all minis
   - Key disagreements or different perspectives
   - Actionable recommendations
