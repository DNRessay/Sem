# SEMBLANCE — Deployment

How the live system is put together and how to deploy it from a phone (GitHub Actions for AWS and the
frontend, Google Colab for Modal). Local development is in [RUNNING.md](./RUNNING.md).

## 1. Architecture

```
Cloudflare Pages (frontend, https://semblance-773.pages.dev)
   │  VITE_API_URL (baked in at build time)
   ▼
Lambda Function URL (RESPONSE_STREAM) ──► semblance-chat   FastAPI under uvicorn via Lambda Web Adapter
                                              │
EventBridge rate(15 minutes) ───────────► semblance-tick   tick_handler.handler
                                              │
        ┌──────────────┬──────────────┬───────┴──────┬──────────────┬─────────────┐
   Neon Postgres   DynamoDB        S3 media       SES (reset     Groq + other   Modal apps
   + pgvector      semblance-cache bucket         emails)        LLM providers  (below)
```

**Frontend** (`frontend/`, Vite + React). Tabs: Chat, Code, Co-work, Design (sub-tabs Ads, Video, Web),
Finance, Bots, Settings (plus an All chats list). Login is a passphrase; `/auth/login` returns a token signed
with `SECRET_KEY`.

**`semblance-chat`** (template.yaml `ChatFunction`): python3.13, x86_64, 1536 MB, 900 s timeout. `run.sh` starts
uvicorn behind the AWS Lambda Web Adapter layer so `/chat` really streams. Function URL with `AuthType: NONE`
and `InvokeMode: RESPONSE_STREAM`; auth is done in the app. IAM: CRUD on the cache table, Put/Get on the
media bucket, SES send from `*@vicinic.co.za`, `ViewOnlyAccess` plus log/metric reads for the read-only AWS
tool, and Lambda/S3 write actions that the app only uses after you tap Approve (stopped once the month's
bill reaches `AWS_SPEND_LIMIT_USD`, default $5).

**`semblance-tick`** (`TickFunction`): 256 MB, 900 s timeout, fires every 15 minutes. Each run
(`tick_handler.py`): one KAIROS tick (due reminders, the morning brief at `KAIROS_BRIEF_HOUR` South Africa
time), the DREAM memory-consolidation gate, a once-a-day refresh of the owner profile
(`tau/pacific.py`), and at most one due Code tab automation.

**Neon Postgres + pgvector**: all records and embeddings (384-dim). `storage/neon_store.py` runs
`CREATE EXTENSION IF NOT EXISTS vector` and creates its own tables on startup.

**DynamoDB `semblance-cache`**: created by the stack, PAY_PER_REQUEST, TTL on `ttl`.

**S3 media bucket** (`MediaBucket`, default `semblance-media-053097418755`): **not created by the stack** — it
must already exist, private, with a lifecycle rule that deletes objects after 7 days. Holds ad images and
videos.

**SES**: passphrase reset emails only (`gateway/reset_router.py`), sent from `SES_FROM_EMAIL` in eu-west-1,
only to addresses in `RESET_EMAILS`. The sender must be verified in SES.

**LLMs**: Groq is primary (`GROQ_MODEL`, `GROQ_PLANNING_MODEL`). When Groq's quota is exhausted the chain is
Bonsai on Modal (`LOCAL_LLM_URL`) → Cohere (`COHERE_API_KEY`) → a "try again in ~N minutes" message.
Gemini, Anthropic, OpenAI, Qwen, DeepSeek, Kimi and Hugging Face appear in the model picker once their key is set.

**MCP server** at `POST /mcp` (`gateway/mcp_router.py`, `gateway/mcp_server.py`). OAuth 2.1 with PKCE
(`gateway/mcp_oauth.py`, `gateway/oauth_router.py`): a client such as Claude's "Add custom connector" gets
401 + `WWW-Authenticate`, discovers `/.well-known/oauth-protected-resource` and
`/.well-known/oauth-authorization-server`, registers at `/oauth/register`, and you sign in with the app
passphrase. The token issued is an ordinary MCP key, revocable in Settings. `/mcp/servers` also manages
outside MCP servers Sem can call (plus any in `MCP_SERVERS`).

### Modal apps

All URLs are `https://<workspace>--...modal.run`. Every app scales to zero.

| App (file) | What it does | Modal secret | Lambda env var |
|---|---|---|---|
| `semblance-embeddings` (`embeddings.py`) | all-MiniLM-L6-v2 embeddings + an emotion classifier, CPU | none | `MODAL_EMBEDDINGS_URL` (the `-embed` URL; emotion URL is derived) |
| `semblance-llm` (`llm.py`) | Ternary Bonsai 2 27B, OpenAI-compatible, L4 GPU, max 1 container, Groq overflow | `semblance-llm-secret` (`LLM_API_KEY`) | `LOCAL_LLM_URL`, `LOCAL_LLM_API_KEY` = `LLM_API_KEY` |
| `semblance-repo-tool` (`repo_tool.py`) | persistent git clones on a Modal Volume; read, grep, bash, ruff, pytest for the Code tab | `semblance-repo-secret` (`REPO_TOOL_SECRET`) | `MODAL_REPO_URL`, `MODAL_REPO_SECRET` = `REPO_TOOL_SECRET` |
| `semblance-video` (`video.py`) | Wan 2.1 (1.3B) 5-second clips, FLUX.1-schnell images when Gemini's image quota runs out, `peek`, and `stitch` to join scenes + voiceover; L4, max 1 GPU, monthly cap | `semblance-video-secret` (`VIDEO_SECRET`, `VIDEO_MONTHLY_CAP_USD`) | `MODAL_VIDEO_URL`, `MODAL_VIDEO_SECRET` = `VIDEO_SECRET` |
| `semblance-voice` (`voice.py`) | Kokoro-82M TTS + Whistle speech-to-text, CPU | reuses `semblance-video-secret` | `VOICE_URL` — derived from `MODAL_VIDEO_URL` unless set; `off` disables |
| `semblance-laya` (`laya.py`) | Laya decision model: per-message yes/no questions (needs repo? web? memory?), CPU | reuses `semblance-video-secret` | `LAYA_URL` — derived from `MODAL_VIDEO_URL` unless set; `off` disables |
| `semblance-searxng` (`searxng.py`) | private SearXNG metasearch, CPU; 404 without the key in the path | `semblance-searxng` (`SEARXNG_KEY`) | `SEARXNG_URL` = printed URL + `/<SEARXNG_KEY>` |

`VOICE_URL` and `LAYA_URL` are not template parameters, so in AWS they are always derived (by replacing
`semblance-video-api` in `MODAL_VIDEO_URL`). If voice is unavailable, TTS falls back to Gemini.

## 2. One-time setup (in this order)

### 2a. Modal secrets and deploys (Colab)

In a Colab cell: `!pip install modal`, `!modal token new` (or `modal setup`), clone the repo, then:

```bash
modal secret create semblance-video-secret VIDEO_SECRET=<random> VIDEO_MONTHLY_CAP_USD=10
HF_TOKEN=<token> modal deploy modal_app/video.py   # accept FLUX.1-schnell's terms on Hugging Face first
modal deploy modal_app/voice.py                      # reuses semblance-video-secret
modal deploy modal_app/laya.py                       # reuses semblance-video-secret

modal deploy modal_app/embeddings.py                 # no secret

modal secret create semblance-repo-secret REPO_TOOL_SECRET=<random>
modal deploy modal_app/repo_tool.py

modal secret create semblance-llm-secret LLM_API_KEY=<random>
modal deploy modal_app/llm.py

modal secret create semblance-searxng SEARXNG_KEY=<long random> --force
modal deploy modal_app/searxng.py
```

Create the video secret first: voice and laya will not start without it. Deploy-time overrides (env vars on
the deploy command): `SEMBLANCE_LLM_GPU`, `SEMBLANCE_LLM_CTX`, `SEMBLANCE_LLM_KV`, `SEMBLANCE_LLM_SCALEDOWN`,
`SEMBLANCE_VIDEO_GPU`, `SEMBLANCE_VIDEO_GPU_RATE`, `SEMBLANCE_VIDEO_MODEL`, `SEMBLANCE_VOICE_SCALEDOWN`,
`SEMBLANCE_LAYA_SCALEDOWN`. Also set a workspace spend limit in Modal's billing settings.

### 2b. AWS

1. Create the media bucket (private, 7-day expiry lifecycle rule) and verify the SES sender.
2. IAM user for CI (e.g. `git`): create [`docs/git-iam-user-policy.json`](./git-iam-user-policy.json) as a
   standalone managed policy and attach it to the user. It has account ID `053097418755` in its ARNs — change
   it for another account. Create an access key ("Application running outside AWS").
3. Neon: create a project and copy the connection string (`...?sslmode=require`).
4. Cloudflare: a Pages project named `semblance` (Direct Upload), an API token that can edit Pages, and the
   account ID.

### 2c. GitHub repository secrets

**Required** (deploy fails or the app won't start without them):

| Secret | Meaning |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | the CI IAM user's key |
| `GROQ_API_KEY` | Groq key, primary LLM |
| `NEON_DATABASE_URL` | Neon connection string |
| `SEMBLANCE_SECRET_KEY` | `SECRET_KEY`, signs login tokens; 32+ random chars (the Lambda refuses to start on `change-me`) |
| `SEMBLANCE_API_URL` | the stack's `ChatFunctionUrl`, used as `VITE_API_URL` for the frontend build |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | frontend deploy |

**Optional** (unset = feature off; the workflow leaves the parameter out):

| Secret | Meaning |
|---|---|
| `AWS_REGION` | defaults to `eu-west-1`; keep it equal to `samconfig.toml`'s region |
| `MODAL_EMBEDDINGS_URL` | embeddings app URL (blank = non-semantic fallback vector) |
| `MODAL_REPO_URL`, `MODAL_REPO_SECRET` | repo tool URL and its `REPO_TOOL_SECRET` |
| `MODAL_VIDEO_URL`, `MODAL_VIDEO_SECRET` | video app URL and `VIDEO_SECRET` (also turns on voice and laya) |
| `LOCAL_LLM_URL`, `LOCAL_LLM_API_KEY` | Bonsai URL and its `LLM_API_KEY` |
| `COHERE_API_KEY` | Cohere trial key, last-resort fallback |
| `GEMINI_API_KEY` | Gemini free tier, Nano Banana images, Gemini TTS |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `QWEN_API_KEY`, `DEEPSEEK_API_KEY`, `KIMI_API_KEY`, `HF_TOKEN` | extra models in the picker |
| `SEARXNG_URL` | SearXNG URL including `/<SEARXNG_KEY>` |
| `SERP_API_KEY` | SerpAPI, used for search when SearXNG isn't set |
| `OWNER_WHATSAPP_NUMBER` | your number (international, no +) for reminders and the brief |
| `KAIROS_BRIEF_HOUR` | brief hour, SA time (default 7) |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | WhatsApp Cloud API send, webhook verify, inbound signature check |
| `OPENCLAW_URL`, `OPENCLAW_WEBHOOK_SECRET` | OpenClaw bridge and the bearer it sends to `/webhook/openclaw` |
| `GH_WEBHOOK_SECRET` | GitHub repo webhook secret (`/webhook/github` refuses everything until set) |
| `RESET_EMAILS` | comma-separated emails allowed to get a reset link |
| `SES_FROM_EMAIL` | verified SES sender (default `SEMBLANCE <noreply@vicinic.co.za>`) |
| `MCP_SERVERS` | JSON `{"name": "base_url"}` of outside MCP servers |
| `GH_OAUTH_CLIENT_ID`, `GH_OAUTH_CLIENT_SECRET` | GitHub OAuth app (callback `{PUBLIC_API_URL}/connectors/github/callback`) |
| `GITLAB_OAUTH_CLIENT_ID`, `GITLAB_OAUTH_CLIENT_SECRET` | GitLab OAuth app |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | Google Calendar/Gmail/Drive/Contacts |

`PublicApiUrl` is hard-coded in `semblance.yml`, as are `GroqModel`, `GroqPlanningModel` and `CohereModel`
(CloudFormation would otherwise reuse old values). Change those lines when the model IDs change.

### 2d. Seed workflows (Actions tab → Run workflow; both need `NEON_DATABASE_URL`)

- **Seed accounts** (`seed-accounts.yml`): secret `OWNER_ACCOUNTS_JSON`, a JSON array, e.g.
  `[{"id": "owner", "passphrase": "...", "role": "owner"}]`. Passphrases are hashed before storage. Login
  checks the `owner` account. Re-running rotates passphrases and signs out old logins and MCP keys.
- **Seed owner profile** (`seed-owner-profile.yml`): secret `OWNER_PROFILE_JSON`, a JSON object merged into
  the owner's profile (`user_models`, key `owner`). Only the keys are printed in the log.

## 3. Deploying

**Backend.** Push to `claude/bold-hawking-8o28g3` (changes under `frontend/`, `docs/` or `*.md` alone don't
trigger it), or run the workflow by hand. `semblance.yml`:
1. Lint & Test on Python 3.13: `ruff check .`, `python -m pytest tests/ -v --tb=short`. Pull requests stop here.
2. Deploy: `sam build`, then `sam deploy` to stack `semblance` with the secrets as parameter overrides
   (trimmed of stray newlines). On failure it prints changeset and stack events.
3. Sets a 14-day expiry on the SAM artifacts bucket.
4. Smoke test: `/health` → 200, `POST /auth/login` with a wrong passphrase → 401, CORS preflight on
   `/auth/login` → < 300, `/connectors` and `/skills` unauthenticated → 401.

Note: `samconfig.toml` has `use_container = true` under build parameters; the workflow runs plain `sam build`.

**Frontend.** `cloudflare-pages.yml` runs on pushes to the same branch that touch `frontend/**` (or the
workflow file), or by hand: Node 20, `npm install`, `npm run build` with `VITE_API_URL=$SEMBLANCE_API_URL`,
checks a `*.on.aws` URL is in the bundle, `wrangler pages deploy` to project `semblance`, then confirms
https://semblance-773.pages.dev serves the new build.

**Modal.** Not in CI. After changing a file in `modal_app/`, in Colab: `modal deploy modal_app/<app>.py`.
URLs stay the same across redeploys, so no GitHub secret changes are needed. `video.py` needs `HF_TOKEN`
in the environment when the image has to rebuild.

## 4. Costs

| Item | Cost |
|---|---|
| Lambda (chat + tick) | usage-based, billed per ms; tick fires 2,880 times a month, mostly no-ops |
| Function URL | no API Gateway in the stack |
| DynamoDB | on-demand; "fractions of a cent/month" for one user (template comment) |
| CloudWatch Logs | usage-based; retention set to 14 days |
| S3 media | usage-based; objects expire after 7 days |
| Neon | free tier |
| Cloudflare Pages | free plan (not stated in code) |
| Modal, overall | $30/month free credit (`MODAL_FREE_CREDIT_USD`), shared by all apps |
| Modal embeddings, repo tool, SearXNG | CPU, scale to zero; "a few cents a month" per their docstrings |
| Modal voice, laya | CPU only (4 and 2 cores), max 1 container, stay warm 10 min after use; usage-based |
| Modal llm (Bonsai) | L4 ~$0.80/hour while awake, 5 min idle before scaling down; only runs when Groq's quota is out |
| Modal video | L4 at `GPU_USD_PER_HOUR` 0.80; new jobs refused once the month's total reaches `VIDEO_MONTHLY_CAP_USD` (default 10) |
| Groq, Gemini, Cohere trial | free tiers; paid providers usage-based when their key is set |

## 5. Troubleshooting

- **Lambda won't start, "SECRET_KEY is unset"**: set `SEMBLANCE_SECRET_KEY` (32+ chars) and redeploy.
- **Modal returns `{"error": "unauthorized"}`**: the Lambda's secret differs from the Modal secret.
  `MODAL_VIDEO_SECRET` must equal `VIDEO_SECRET` (video, voice, laya), `MODAL_REPO_SECRET` must equal
  `REPO_TOOL_SECRET` (the Code tab says so). Fix the GitHub secret and redeploy, or recreate the Modal
  secret with `--force` and redeploy that app. For Bonsai, `LOCAL_LLM_API_KEY` must equal `LLM_API_KEY`
  (llama-server's `--api-key`); a mismatch fails silently and the overflow skips straight to Cohere.
- **"Monthly video budget reached ($x of $y)"** (or "Monthly Modal budget reached" for images): raise
  `VIDEO_MONTHLY_CAP_USD` in `semblance-video-secret` and redeploy `video.py`, or wait for next month.
- **Groq rate limit**: replies prefixed "answered by the self-hosted backup model" or "answered via Cohere
  fallback" are expected. A "try again in ~N minutes" reply means Bonsai and Cohere are also unset or failed.
  The first Bonsai reply after idle waits for the GPU to wake.
- **Voice or laya silent**: they need `MODAL_VIDEO_URL` to contain `semblance-video-api` and their apps deployed.
- **Login fails with 401 everywhere**: run Seed accounts. 429 means too many wrong tries; wait 15 minutes
  or use the reset email.
- **Frontend calls the wrong URL**: the build fails at "Verify baked API URL" if `SEMBLANCE_API_URL` is empty.
- **Deploy "succeeded" but nothing changed**: check the parameter was set as a secret; omitted parameters
  keep their previous deployed value.
- **CloudWatch** (`/aws/lambda/semblance-chat`), grep for:
  - `llm ` — which provider answered and how long it took, or why it failed;
  - `tts ` — `tts kokoro …` or `tts gemini … (kokoro: <reason>)`;
  - `chat context ready` — time spent on routing, memory and skills before the model was called.
  Tick output is in `/aws/lambda/semblance-tick`.
