# SEMBLANCE on AWS — Deployment Guide

Single-user deployment, designed to cost a few rand a month, never more than
about R59 even under generous assumptions. No Render, no Aiven, no ChromaDB.

## Architecture

```
React frontend (Cloudflare Pages, free)
        │  VITE_API_URL
        ▼
Lambda Function URL  ──────────────►  ChatFunction (Light tier)
  (no API Gateway)                     FastAPI + Mangum
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              Neon Postgres      DynamoDB cache        Modal (embeddings)
              + pgvector         (TTL, pay-per-req)     sentence-transformers
              (memories, convos,                        scales to zero
               user models, vectors — one database)

EventBridge (rate: 15 min) ──────────► TickFunction (Medium tier)
                                        one KAIROS tick per firing
                                        (replaces the always-on daemon loop)

Groq API ── Qwen3-32B (chat) + DeepSeek-R1-Distill-70B (ULTRAPLAN) — free tier
```

Nothing runs continuously. There is no Heavy tier in this deployment — KAIROS's
`start()` infinite loop, PROACTIVE, UDS inbox, and BRIDGE all require an
always-on process (EC2/Fargate) to be meaningful, and an always-on box is
the one thing that reliably breaks a near-zero budget. They're left in the
codebase as documented, deliberate future work — see the table at the bottom.

## Why these choices

| Decision | Why |
|---|---|
| Lambda **Function URL**, not API Gateway | API Gateway HTTP APIs are free for the first 12 months, then ~$1/million requests. Function URLs have no request charge, ever, and no cliff to fall off. |
| **arm64** (Graviton) Lambda | ~20% cheaper per ms than x86_64 for the same work — free either way at this volume, but no reason not to. |
| **Neon** instead of Aiven MySQL | Same "always free" positioning, but adds pgvector — one database instead of two services. |
| **pgvector** instead of ChromaDB | ChromaDB's `PersistentClient` writes to local disk, which doesn't exist reliably in Lambda (`/tmp` is wiped on cold start, not shared across concurrent invocations). pgvector rides on the database you already have. |
| **DynamoDB** for cache, not in-memory only | An in-memory dict resets every cold start. DynamoDB's native per-item TTL means expiring cache entries need no cron job. An in-memory L1 sits in front of it so warm invocations never leave the process. |
| **Modal** for embeddings | sentence-transformers is a few hundred MB and slow to load — bad for Lambda cold starts. Modal scales to zero between calls and has a standing $30/month free credit that a single user won't come close to using. |
| **EventBridge schedule**, not a daemon | KAIROS's `while True` loop can't survive Lambda freezing the process between invocations. A scheduled Lambda firing every 15 minutes gets you the same "checks in periodically" behavior without an always-on box. |
| **PAY_PER_REQUEST** DynamoDB, not provisioned | The "25 WCU/RCU always free" tier is for provisioned capacity; on-demand has no free tier but costs $1.25/$0.25 per million write/read units — at one user's volume this is fractions of a cent, and there's no capacity to under/over-provision. |

## What this does NOT include (by design)

- **UNDERCOVER / SHADOW TOOL** were removed entirely — identity masking and
  attribution stripping are ToS-violation territory on most platforms and a
  real ban risk for both the hosting account and any connected service. Don't
  reintroduce them.
- **The "free-code" CLI wrapper** that used to sit between Bootstrap and Groq,
  passing a spoofed `claude-sonnet-4-6` model string while actually calling
  Groq, is gone. `pipeline/bootstrap.py` now calls `QueryEngine` directly —
  whatever model answered is the model reported, no impersonation of any
  vendor's model.
- **KAIROS/PROACTIVE/BRIDGE/UDS inbox** (Heavy tier) are not deployed. They
  need an always-on process; that's real 24/7 compute cost. If you want them
  later, the cheapest path is a single `t4g.nano` or `t4g.micro` EC2 instance
  running just those four components, calling the Lambda for everything else
  — see `SEMBLANCE-TIERS.md`. That's the point at which you'd start
  approaching (not exceeding) the R59 ceiling.

## Setup

### 1. Accounts (all free to create)

- **Groq** — console.groq.com → API key. Free tier, no card required.
- **Neon** — neon.tech → new project → copy the pooled connection string
  (`postgresql://...?sslmode=require`). Free tier: 0.5 GB storage, autosuspend
  after inactivity (expect an extra ~1s cold-start after idle periods — a
  fair trade for $0).
- **Modal** — modal.com → `pip install modal && modal setup` (device-code
  login, no separate account creation needed beyond that).
- **AWS** — you already have this if you're reading this from inside AWS
  docs. Use a dedicated IAM role for deploys (below), never your root user.

### 2. Deploy the embeddings function to Modal

```bash
pip install modal
modal setup
modal deploy modal_app/embeddings.py
```

Copy the printed URL into `MODAL_EMBEDDINGS_URL`.

### 3. First deploy (local, guided)

```bash
pip install aws-sam-cli
sam build --use-container     # container build = correct arm64/py3.13 wheels for asyncpg etc.
sam deploy --guided
```

Answer the parameter prompts (Groq key, Neon URL, Modal URL, a secret key you
invent for `x-api-key`). This writes your answers into `samconfig.toml`
locally — **do not commit real secret values there**; the checked-in
`samconfig.toml` only has non-secret deploy settings, secrets are meant to
come from `--parameter-overrides` (CI) or your local untracked answers file.

Take the `ChatFunctionUrl` output and set it as `VITE_API_URL` for the
frontend build.

### 4. CI/CD (GitHub Actions → AWS via an IAM user access key)

This repo authenticates as an existing IAM user (named e.g. `git`) using a
static access key pair, rather than an OIDC role. Simpler to set up; the
trade-off is that leaked key works from anywhere, not just GitHub's runners
— rotate it periodically and scope its policy tightly. (If you'd rather not
manage that, the OIDC role approach avoids storing any long-lived key at
all — ask if you want to switch later, it's a small workflow change.)

1. On the `git` IAM user, attach a policy covering: Lambda, DynamoDB (on the
   cache table), CloudFormation (SAM deploys via a changeset), IAM (to
   manage the two function execution roles), S3 (SAM's deployment bucket),
   Logs. Scope resource ARNs to the `semblance-*` stack rather than `*`
   where the console lets you.
2. Generate an access key for that user (IAM console → the user → Security
   credentials → Create access key → "Application running outside AWS" /
   CLI). You get an **Access Key ID** and a **Secret Access Key** — the
   secret is shown once, copy it immediately.
3. Add these **repository secrets** (Settings → Secrets and variables →
   Actions → New repository secret):
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_REGION` — e.g. `us-east-1`
   - `GROQ_API_KEY`
   - `NEON_DATABASE_URL`
   - `MODAL_EMBEDDINGS_URL`
   - `SEMBLANCE_SECRET_KEY`
   - `SERP_API_KEY`, `OPENCLAW_URL` (optional — leave the secret unset and
     the workflow passes an empty string, which disables those features
     cleanly)
4. Push to `claude/bold-hawking-8o28g3` (this repo's trunk branch —
   there's no separate `main`). `.github/workflows/semblance.yml` lints, tests, then
   deploys — in that order, so a broken build never reaches AWS.

### 5. Frontend (Cloudflare Pages)

`frontend/` is a Vite + React app. Local dev:

```bash
cd frontend
npm install
cp .env.example .env   # set VITE_API_URL to your ChatFunctionUrl (or localhost:8000)
npm run dev
```

**One-time Cloudflare setup:**
1. Cloudflare dashboard → Workers & Pages → create a Pages project named
   `semblance` (matches `projectName` in
   `.github/workflows/cloudflare-pages.yml`) — connecting it to a "Direct
   Upload" project is enough since GitHub Actions does the building and
   pushing, not Cloudflare's own Git integration.
2. Create an API token (My Profile → API Tokens → "Edit Cloudflare
   Workers" template covers Pages) and note your Account ID (right sidebar
   of any dashboard page).
3. Add repository secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
   `SEMBLANCE_API_URL` (your `ChatFunctionUrl` — baked into the static
   build at build time, since Vite env vars aren't runtime-configurable
   after the fact).
4. Push to `claude/bold-hawking-8o28g3` (touching anything under `frontend/`) and
   `.github/workflows/cloudflare-pages.yml` builds and deploys it.

Cloudflare Pages free tier: unlimited requests/bandwidth, 500 builds/month.
For one user, $0.

**Known gap:** `AgentFeed.jsx` polls `/status/{session_id}` expecting
`{event: {...}}` objects, but `gateway/router.py`'s `/status` endpoint
currently just returns `{"status": "active"}` — the panel renders fine, it
just always says "No activity yet". Wiring real agent-activity events
through there is follow-up work, not a broken build.

## Cost breakdown (single user, realistic traffic)

| Component | Pricing | Estimated monthly cost |
|---|---|---|
| Lambda (ChatFunction + TickFunction) | 1M requests + 400,000 GB-s free forever | $0 |
| Lambda Function URL | No charge, ever | $0 |
| EventBridge schedule (2,880 firings/mo) | Free for rules targeting Lambda | $0 |
| DynamoDB (PAY_PER_REQUEST) | $1.25/$0.25 per million write/read units | < $0.01 |
| CloudWatch Logs (14-day retention set) | 5 GB ingest + 5 GB storage free tier | $0 |
| Neon Postgres + pgvector | Free tier (0.5 GB, autosuspend) | $0 |
| Modal embeddings | $30/month credit; single-user usage is a rounding error against it | $0 |
| Groq (Qwen3-32B, DeepSeek-R1) | Free tier | $0 |
| Frontend (Cloudflare Pages) | Free (unlimited requests, 500 builds/mo) | $0 |
| **Total** | | **~$0.00–0.05/month** |

At any realistic ZAR/USD rate that's a few cents to a few rand — well under
the R15 target, nowhere near R59. The only way this creeps up is a custom
domain (Route 53 hosted zone ≈ $0.50/month + registration ≈ $12/year) or
adding the Heavy tier back with a real EC2 instance running 24/7 — both
optional, neither required for what's deployed here.
