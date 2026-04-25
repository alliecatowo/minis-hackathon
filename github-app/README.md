# Minis GitHub App

A GitHub App that enables [minis](../backend/) (AI personality clones) to review pull requests in character.

## How It Works

1. Install the Minis GitHub App on your repository
2. When a PR is opened, if any requested reviewers have minis, the app asks the backend for a structured review prediction and posts it
3. You can @mention a mini in PR comments for on-demand review: `@alliecatowo-mini can you review this?`
4. The review output reflects the mini's predicted review stance, comments, and priorities

## Setup

### 1. Create a GitHub App

Go to **GitHub Settings > Developer settings > GitHub Apps > New GitHub App** and configure:

- **Name**: `minis-pr-reviewer` (or your choice)
- **Homepage URL**: `https://github.com/alliecatowo/minis-ai`
- **Webhook URL**: Your server URL + `/webhooks/github` (use smee.io or ngrok for local dev)
- **Webhook secret**: Generate a random secret

**Permissions:**
- Pull requests: Read & Write
- Issues: Read & Write

**Events to subscribe to:**
- Pull request
- Issue comment
- Pull request review comment

### 2. Generate a Private Key

On the GitHub App settings page, click "Generate a private key". Save the `.pem` file.

### 3. Configure Environment

Create a `.env` file:

```bash
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY=/path/to/your-app.private-key.pem
GITHUB_WEBHOOK_SECRET=your-webhook-secret
MINIS_API_URL=http://localhost:8000
```

Or set `GITHUB_PRIVATE_KEY` to the PEM contents directly (useful for deployment).

### 4. Install Dependencies

```bash
cd github-app
uv sync
```

### 5. Run the Server

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 6. Local Development with smee.io

For local webhook delivery:

```bash
npx smee-client --url https://smee.io/YOUR_CHANNEL --target http://localhost:8001/webhooks/github
```

### 7. Install the App

Go to your GitHub App's page and click "Install App". Select the repositories you want to enable.

## Usage

### Auto-review on PR open

When a PR is opened with requested reviewers who have minis, the app requests a structured review prediction from the Minis backend and posts it as a GitHub review comment.

### On-demand @mention

Comment on any PR with `@username-mini` to trigger a structured review prediction:

```
@alliecatowo-mini can you review this PR?
@alliecatowo-mini what do you think about the error handling here?
```

## Architecture

```
github-app/
  app/
    main.py       -- FastAPI webhook server + signature verification
    webhooks.py   -- Event handlers (PR opened, comments, mentions)
    github_api.py -- GitHub API client (JWT auth, fetch PRs, post reviews)
    review.py     -- Review-prediction client (fetch mini, call backend, format output)
    config.py     -- Settings from environment
```

The app is a thin webhook handler. The heavy lifting is:
- **Mini lookup**: Fetched from the Minis backend API (`GET /api/minis/by-username/{username}`)
- **Review prediction**: Requested from the Minis backend API (`POST /api/minis/{id}/review-prediction`)
- **GitHub API**: Posts reviews as the GitHub App bot, signed with the mini's name
