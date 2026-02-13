# Deploy Your Own Minis

This guide walks you through deploying your own instance of Minis with:

- **[Neon](https://neon.tech)** — Serverless PostgreSQL with branching
- **[Fly.io](https://fly.io)** — Backend API hosting
- **[Vercel](https://vercel.com)** — Frontend hosting

The result: Every PR gets its own preview environment with an isolated database branch.

## Prerequisites

- GitHub account
- [Fly.io account](https://fly.io/app/sign-up) with CLI installed (`curl -L https://fly.io/install.sh | sh`)
- [Neon account](https://neon.tech)
- [Vercel account](https://vercel.com)

## Step 1: Fork and Clone

```bash
git clone https://github.com/YOUR_USERNAME/minis-hackathon.git
cd minis-hackathon
```

## Step 2: Create Neon Database

1. Go to [Neon Console](https://console.neon.tech) and create a new project
2. Name it `minis` and note your **Project ID** (in the URL: `console.neon.tech/app/projects/YOUR_PROJECT_ID`)
3. Copy the connection string from the dashboard
4. Create an API key at [Neon Account Settings](https://console.neon.tech/account/settings)

Save these for GitHub secrets:
- `NEON_PROJECT_ID` — Your Neon project ID
- `NEON_API_KEY` — Your Neon API key

## Step 3: Deploy Backend to Fly.io

```bash
cd backend

# Create the app (don't deploy yet)
fly apps create minis-api-YOUR_NAME

# Set secrets
fly secrets set GEMINI_API_KEY=your_key
fly secrets set GITHUB_TOKEN=your_gh_pat
fly secrets set JWT_SECRET=$(openssl rand -hex 32)
fly secrets set SERVICE_JWT_SECRET=$(openssl rand -hex 32)
fly secrets set NEON_DATABASE_URL="postgresql+asyncpg://..."

# Update fly.toml to use your app name, then deploy
fly deploy
```

Create a Fly API token:
```bash
fly tokens create deploy -x
```

Save for GitHub secrets:
- `FLY_API_TOKEN` — The token from above

## Step 4: Deploy Frontend to Vercel

```bash
cd frontend

# Link to Vercel
vercel link

# Set environment variables in Vercel dashboard or CLI:
vercel env add BACKEND_URL
# Enter: https://minis-api-YOUR_NAME.fly.dev

vercel env add AUTH_GITHUB_ID
vercel env add AUTH_GITHUB_SECRET
vercel env add AUTH_SECRET
vercel env add SERVICE_JWT_SECRET  # Must match backend
vercel env add NEXT_PUBLIC_API_URL  # https://minis-api-YOUR_NAME.fly.dev

# Deploy
vercel --prod
```

Get Vercel tokens/IDs:
```bash
# From frontend/.vercel/project.json or:
vercel project ls
```

Save for GitHub secrets:
- `VERCEL_TOKEN` — Create at vercel.com/account/tokens
- `VERCEL_ORG_ID` — Your team/user ID
- `VERCEL_PROJECT_ID` — From `.vercel/project.json`

## Step 5: Configure GitHub Secrets

Go to your repo → Settings → Secrets and variables → Actions

Add these secrets:

| Secret | Where to get |
|--------|-------------|
| `FLY_API_TOKEN` | `fly tokens create deploy -x` |
| `NEON_API_KEY` | Neon Console → Account Settings |
| `NEON_PROJECT_ID` | URL of your Neon project |
| `VERCEL_TOKEN` | vercel.com/account/tokens |
| `VERCEL_ORG_ID` | `.vercel/project.json` or `vercel project ls` |
| `VERCEL_PROJECT_ID` | `.vercel/project.json` |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com) |
| `GITHUB_TOKEN` | GitHub PAT with `read:user`, `repo` scopes |
| `JWT_SECRET` | `openssl rand -hex 32` |
| `SERVICE_JWT_SECRET` | Same value as set in Fly |

## Step 6: Update Workflow Files

Edit `.github/workflows/preview.yml`:

```yaml
# Line 48: Update this to your Vercel preview URL pattern
| **Frontend** | https://${{ github.head_ref }}--YOUR_VERCEL_APP.vercel.app |
```

Edit `backend/fly.toml`:

```toml
app = "minis-api-YOUR_NAME"  # Change to your Fly app name
```

## Step 7: Push and Verify

```bash
git add .
git commit -m "Configure deployment for my instance"
git push origin main
```

Check the Actions tab — you should see the Deploy workflow running.

## What You Get

- **Production**: Merged PRs auto-deploy to Fly + Vercel
- **Previews**: Each PR gets:
  - Neon database branch (`pr-42`)
  - Fly review app (`minis-api-pr-42.fly.dev`)
  - Vercel preview pointing to Fly review app
- **Cleanup**: Closing a PR deletes all preview resources

## Troubleshooting

### Fly deployment fails
```bash
fly logs -a minis-api-YOUR_NAME
```

### Neon branch creation fails
- Check `NEON_API_KEY` has the right permissions
- Verify `NEON_PROJECT_ID` is correct

### Vercel preview not connecting to backend
- Ensure `BACKEND_URL` environment variable is set for preview environment
- Check CORS settings in backend include your Vercel preview URL

## Cost Estimate

| Service | Free Tier | Estimated Paid |
|---------|-----------|----------------|
| Neon | 0.5 GB storage, 100 branches | ~$0 (free tier covers dev) |
| Fly.io | 3 VMs, 3GB volume | ~$5-10/mo for production |
| Vercel | 100GB bandwidth | ~$0 for personal projects |

**Total: Likely free for personal use, ~$5-15/mo for production workloads.**
