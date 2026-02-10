---
allowed-tools: Bash(curl:*)
description: Create a new developer mini from a GitHub username. Usage: /mini-create <username>
---

## Your Task

The user wants to create a new developer mini (AI personality clone). The arguments provided are: $ARGUMENTS

**Follow these steps exactly:**

1. **Parse the arguments.** The first argument is the GitHub username. If no username is provided, ask the user for a GitHub username and stop.

2. **Check if the mini already exists.** Run:
   ```
   curl -s http://localhost:8000/api/minis/<username>
   ```
   If the mini exists and status is `ready`, inform the user:
   > The mini for @<username> already exists and is ready. Use `/mini-chat <username>` to chat or `/mini-review <username>` to get a code review.

   If status is `processing`, inform them it is still being created.

3. **Create the mini.** Run:
   ```
   curl -s -X POST http://localhost:8000/api/minis \
     -H "Content-Type: application/json" \
     -d '{"username": "<username>"}'
   ```

4. **Monitor progress.** Poll the mini's status every 5 seconds:
   ```
   curl -s http://localhost:8000/api/minis/<username>
   ```
   Report each status change to the user. The pipeline stages are:
   - **fetch**: Fetching GitHub activity (commits, PRs, reviews, issues)
   - **format**: Formatting evidence for analysis
   - **extract**: Analyzing personality and engineering values
   - **synthesize**: Synthesizing personality document and system prompt
   - **save**: Saving the mini to the database

   Continue polling until status is `ready` or `failed`.

5. **Report completion.** When status is `ready`, display:
   > Mini for @<username> (<display_name>) is ready!
   >
   > Use `/mini-chat <username>` to start a conversation.
   > Use `/mini-review <username>` to get a code review.

   If `failed`, report the failure and suggest trying again.
