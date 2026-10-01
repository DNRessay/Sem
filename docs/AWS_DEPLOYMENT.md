# SEMBLANCE on AWS — Deployment Guide

Single-user deployment, designed to cost a few rand a month, never more than
about R59 even under generous assumptions. No Render, no Aiven, no ChromaDB.

## Architecture

```
React frontend (Cloudflare Pages, free)
        │  VITE_API_URL
        ▼
Lambda Function URL  ──────────────►  ChatFunction (Light tier)
  (no API Gateway,                     FastAPI + uvicorn,
   RESPONSE_STREAM)                    via Lambda Web Adapter
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

Groq API ── Qwen3.8-27B (chat) + GPT-OSS-120B (ULTRAPLAN) — free tier
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
| **x86_64** Lambda, not arm64/Graviton | Graviton is ~20% cheaper per ms, but building it needs cross-architecture container emulation (QEMU) — GitHub-hosted CI runners don't reliably have that set up, and the first real deploy hit exactly this as a build failure risk. x86_64 matches the CI runner natively. At ~$0/month usage either way, reliability wins. |
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

### 2b. Deploy the persistent repo-clone tool to Modal (optional)

Powers "Add repo" keeping a real clone around between questions, instead of
just a one-shot text dump. Skip this step entirely and everything else still
works — "Add repo" degrades to the one-shot dump.

```bash
modal secret create semblance-repo-secret REPO_TOOL_SECRET=<invent-any-random-string>
modal deploy modal_app/repo_tool.py
```

Copy the printed URL into `MODAL_REPO_URL`, and the same random string you
invented above into `MODAL_REPO_SECRET` — they must match, since (unlike the
embeddings endpoint) this one can clone private repos and read arbitrary
files out of them, so it needs real auth, not just an unguessable URL.

### 2c. Deploy the self-hosted backup model to Modal (optional)

Ternary Bonsai 2 27B (same Qwen3.8-27B base as the Groq chat model) on an L4
GPU. Sem uses it when Groq's daily/hourly quota runs out, before the Cohere
trial key. The same endpoint works for a coding CLI such as MiniMax Code. It
scales to zero, so the first reply after an idle spell waits about a minute.

```bash
modal secret create semblance-llm-secret LLM_API_KEY=<invent-any-random-string>
modal deploy modal_app/llm.py    # first deploy also downloads ~7 GB of weights into the image
```

Copy the printed URL into `LOCAL_LLM_URL` and the random string into
`LOCAL_LLM_API_KEY`. Then set a hard spend limit in Modal's billing
settings: at roughly $0.80/hour awake, the $30 credit buys about 35 GPU
hours a month, shared with embeddings.

### 2d. Code tab (optional)

The Code tab works in an editable clone on the same Modal repo service from
step 2b, so redeploy that after pulling: `modal deploy modal_app/repo_tool.py`.
It uses the backup model from step 2c when configured (no per-minute token
cap), otherwise Groq. Opening PRs uses your GitHub/GitLab connector token.
The agent's read-only `aws` tool uses the chat Lambda's own role: attach
AWS's `ViewOnlyAccess` managed policy to that role if you want it to see more
than Sem's own resources.

### 2e. Video ads (optional, costs GPU time)

The Design tab's video ads run Wan 2.1 (open source) on an L4 GPU, with a
hard monthly cap enforced on the Modal side:

```bash
modal secret create semblance-video-secret VIDEO_SECRET=<invent-any-random-string> VIDEO_MONTHLY_CAP_USD=10
modal deploy modal_app/video.py    # first deploy downloads ~15 GB of model weights
```

Set `MODAL_VIDEO_URL` and `MODAL_VIDEO_SECRET` (GitHub secrets of the same names).

### 2f. Model and media keys (all optional)

Add any of these as GitHub secrets; each provider appears in the model
picker once its key is set. "Auto" uses only the free ones.

| Secret | Gives you |
|---|---|
| `GEMINI_API_KEY` | Gemini free tier in the picker, Nano Banana images (Design/Co-work), read-aloud voice |
| `ANTHROPIC_API_KEY` | Claude (paid) |
| `OPENAI_API_KEY` | GPT (paid) |
| `QWEN_API_KEY` | Qwen via Alibaba Cloud Model Studio (paid) |
| `DEEPSEEK_API_KEY` / `KIMI_API_KEY` | DeepSeek / Kimi (paid) |
| `HF_TOKEN` | Any chat model on Hugging Face's router, picked by repo id |

Web search needs no key: it tries `SEARXNG_URL` (any SearXNG server you
run), then SerpAPI, then the open-source `ddgs` package.

### 2g. MCP (optional)

- **Use Sem from other apps:** Settings → "Create MCP key" shows a ready-to-paste
  `claude mcp add ...` command and a JSON config for other MCP clients. Sem's
  endpoint is `<PUBLIC_API_URL>/mcp`.
- **Give Sem other MCP servers:** Settings → "MCP servers Sem can use". Their
  tools appear in Co-work and Code; tick "ask me first" to get approval cards.
  `MCP_SERVERS` (JSON, `{"name": {"url": ..., "auth": ...}}`) still works for
  servers every account should share.

### 2h. Background jobs

One EventBridge schedule (every 15 minutes, free) runs KAIROS (due
reminders + the morning brief at `KAIROS_BRIEF_HOUR`), DREAM, and one due
Code automation per tick. Briefs and reminders always appear in the app as
chats; set `OWNER_WHATSAPP_NUMBER` to also get them on WhatsApp. Nothing is
scheduled on GitHub Actions — its terms limit Actions to building, testing
and deploying the repo.

Modal GPU/model choices are deploy-time env vars: `SEMBLANCE_LLM_GPU`,
`SEMBLANCE_LLM_CTX`, `SEMBLANCE_VIDEO_GPU`, `SEMBLANCE_VIDEO_MODEL`,
`SEMBLANCE_VIDEO_GPU_RATE`.

### 3. First deploy (local, guided)

```bash
pip install aws-sam-cli
sam build --use-container     # container build = correct x86_64/py3.13 wheels for asyncpg etc.
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

1. Create the policy in
   [`docs/git-iam-user-policy.json`](./git-iam-user-policy.json) as a
   **standalone managed policy** — IAM console → Policies → Create policy
   → JSON tab → paste it in → name it `SemblanceDeployPolicy` → Create.
   Then attach it: Users → `git` → Permissions tab → Add permissions →
   Attach existing policies directly → select `SemblanceDeployPolicy`.

   Not an inline policy on the user: IAM sums *every* inline policy on a
   user against one shared 2,048-character budget, and this account's
   `git` user already has enough other inline policy content that even
   this ~980-character policy alone pushed the combined total over the
   limit. A standalone managed policy gets its own separate 6,144-character
   allowance instead of competing for that shared budget, which sidesteps
   the problem entirely rather than trying to shrink further.

   It uses a per-service wildcard action (`cloudformation:*`, `s3:*`,
   `lambda:*`, etc.) rather than enumerating individual actions — the
   resource ARNs are still scoped to `semblance-*` (or the
   `aws-sam-cli-managed-default` bootstrap stack SAM creates for its
   deployment bucket) rather than `*`, so it can't touch anything outside
   those specific stacks/functions/tables/roles even though the action
   side is broad. Reasonable for a personal, single-user AWS account;
   tighten the actions further if this account ever has more than one
   person with access to it. It has the account ID from this repo's own
   first deploy attempt baked into the resource ARNs — swap it if you're
   deploying to a different AWS account.

   First-ever deploy bootstraps more than a routine one (creating the SAM
   managed bucket from scratch), so it's the run most likely to still hit
   a missing permission — if it does, the AccessDenied error names the
   exact service, and it's already covered by that service's wildcard
   here, so a genuinely new denial at this point would mean a service
   this policy doesn't list at all (unlikely, but tell me and I'll add it).
2. Generate an access key for that user (IAM console → the user → Security
   credentials → Create access key → "Application running outside AWS" /
   CLI). You get an **Access Key ID** and a **Secret Access Key** — the
   secret is shown once, copy it immediately.
3. Add these **repository secrets** (Settings → Secrets and variables →
   Actions → New repository secret):
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_REGION` — `eu-west-1` (Ireland — must match `samconfig.toml`'s
     `region`, which SAM reads before this secret; changing one without
     the other silently deploys to the wrong region)
   - `GROQ_API_KEY`
   - `NEON_DATABASE_URL`
   - `MODAL_EMBEDDINGS_URL`
   - `SEMBLANCE_SECRET_KEY`
   - `SERP_API_KEY`, `OPENCLAW_URL`, `MODAL_REPO_URL`, `MODAL_REPO_SECRET`
     (all optional — leave a secret unset and the workflow passes an empty
     string, which disables that feature cleanly)
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

## Cost hygiene — don't let unused stuff quietly accumulate

A near-zero deploy stays near-zero only if old data doesn't pile up
somewhere nobody's looking. What's already handled automatically:

- **CloudWatch Logs**: `template.yaml` sets `RetentionInDays: 14` on both
  functions' log groups explicitly — Lambda's default (no retention set)
  is "never expire," which is the classic slow leak.
- **SAM's deployment bucket**: `sam deploy --resolve-s3` keeps every
  historical build zip forever by default. The deploy workflow now applies
  a 14-day expiration lifecycle rule to that bucket on every deploy (see
  `.github/workflows/semblance.yml`) — old artifacts age out on their own.
- **DynamoDB cache**: every item already carries a short TTL (minutes to an
  hour, per cache type) — nothing accumulates there by design.

What to check by hand occasionally (a few minutes, every month or so is
plenty for one user's traffic):
- **CloudFormation console** → any stack besides `semblance` and
  `aws-sam-cli-managed-default` (the SAM bootstrap stack) that you don't
  recognize — a half-finished deploy from a build that failed partway
  through can leave a stack sitting in `ROLLBACK_COMPLETE`, which itself
  doesn't cost anything, but its resources are also just dead weight.
  Delete it from the console (or `aws cloudformation delete-stack`) if you
  find one — the next `sam deploy` recreates `semblance` clean either way.
- **Neon dashboard** → storage usage, if you're ever near the 0.5 GB free
  tier ceiling (permanent memory means this grows, if slowly, forever by
  design — that's the point of the memory philosophy, but it's worth an
  occasional glance).

**If you change region** (this project moved from `us-east-1` to
`eu-west-1` after a mismatch between `samconfig.toml` and the `AWS_REGION`
secret meant the first deploy landed in the wrong one): CloudFormation
stacks are region-locked, there's no "move" — the old region's stack keeps
existing, and its resources, until you delete it. After confirming the new
region's stack is up and working, clean up the old one:
```bash
aws cloudformation delete-stack --stack-name semblance --region us-east-1
# once that's gone, if nothing else uses the SAM bootstrap bucket there:
aws cloudformation delete-stack --stack-name aws-sam-cli-managed-default --region us-east-1
```

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
| Groq (Qwen3.8-27B, GPT-OSS-120B) | Free tier | $0 |
| Modal backup model (optional, step 2c) | ~$0.80/hour only while awake, capped at one GPU | $0 until Groq runs out |
| Frontend (Cloudflare Pages) | Free (unlimited requests, 500 builds/mo) | $0 |
| **Total** | | **~$0.00–0.05/month** |

At any realistic ZAR/USD rate that's a few cents to a few rand — well under
the R15 target, nowhere near R59. The only way this creeps up is a custom
domain (Route 53 hosted zone ≈ $0.50/month + registration ≈ $12/year) or
adding the Heavy tier back with a real EC2 instance running 24/7 — both
optional, neither required for what's deployed here.
