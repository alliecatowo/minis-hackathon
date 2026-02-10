---
allowed-tools: Bash(curl:*), Bash(git diff:*), Bash(git status:*), Bash(git log:*)
description: Get a code review from a developer mini (AI personality clone). Usage: /mini-review <username> [file_or_scope]
---

## Context

- Git diff of current changes: !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Repository: !`basename $(git rev-parse --show-toplevel)`

## Your Task

The user wants a code review from a developer mini. The arguments provided are: $ARGUMENTS

**Follow these steps exactly:**

1. **Parse the arguments.** The first argument is the GitHub username of the mini to use as reviewer. If no username is provided, list available minis by running:
   ```
   curl -s http://localhost:8000/api/minis | jq -r '.[] | select(.status == "ready") | "  - \(.username) (\(.display_name // .username))"'
   ```
   Then ask the user which mini to use and stop.

2. **Fetch the mini's personality.** Run:
   ```
   curl -s http://localhost:8000/api/minis/<username>
   ```
   If the response is a 404, tell the user the mini does not exist and suggest `/mini-create <username>`. If the status is not `ready`, inform the user the mini is still processing.

3. **Get the diff to review.** Use the git diff from the context above. If a second argument was provided (a file path or scope), filter the diff to only that file:
   ```
   git diff HEAD -- <file_path>
   ```

4. **Send the diff for review.** Send the diff to the mini's chat endpoint:
   ```
   curl -s -N -X POST http://localhost:8000/api/minis/<username>/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Please review the following code changes. Be specific about what is good and what could be improved. Stay in character.\n\n```diff\n<DIFF_CONTENT>\n```", "history": []}'
   ```
   Collect the SSE response chunks (lines starting with `data: ` after `event: chunk`) and concatenate them.

5. **Format and display the review.** Present the review with a header showing the mini's name and a divider. Example:

   ```
   ## Code Review by <display_name> (@<username>)

   <review content from the mini>
   ```
