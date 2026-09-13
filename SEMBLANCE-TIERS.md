# SEMBLANCE — Service Tier Map

Purpose: split the monolith by how "awake" each piece needs to be. This drives
*where* each piece gets deployed. See `docs/AWS_DEPLOYMENT.md` for the actual
deploy instructions — this doc explains the reasoning behind the split.

## Tier definitions

| Tier | Behavior | Platform | Cost shape |
|---|---|---|---|
| **Light** | Sleeps by default. Wakes on invocation, responds, goes back to sleep. No background loop, no persistent in-memory state required between calls. | AWS Lambda | Pay per call (effectively $0 at one user's volume, free tier) |
| **Medium** | Runs on a schedule or trigger, not continuously. Not invoked synchronously by a caller waiting on it — it does a job and stops. | Lambda on an EventBridge schedule | Pay per run (effectively $0) |
| **Heavy** | Must stay running continuously — holds an open loop, a live socket, or a long-lived connection pool that can't be recreated per-request without breaking. | EC2 / Fargate (persistent service) | Pay 24/7 — the one tier that costs real money |

**This deployment ships Light + Medium only.** Heavy tier (KAIROS's continuous
loop, PROACTIVE, UDS inbox, BRIDGE) is documented but not deployed — see
below.

---

## Light — deployed to Lambda (ChatFunction)

Stateless-per-call: given a request, produce a response, done.

| Component | File(s) | Why Light |
|---|---|---|
| Gateway router + webhooks | `gateway/router.py`, `gateway/webhooks.py` | Classic HTTP request/response. |
| Core router | `core/cables_man.py` | Classifies + routes a single task. No loop. |
| Pipeline steps | `pipeline/*.py` | Each is a step in handling one request. |
| Most agents | `agents/base_agent.py`, `buddy.py`, `coordinator.py`, `explore.py`, `general_agent.py`, `guide_agent.py`, `plan_agent.py`, `ultraplan.py`, `dream_agent.py` | Called per-task, return a result, done. |
| TAU | `tau/tau_engine.py`, `tau/pacific.py`, `tau/tau_cache.py` | Per-turn trait inference + cache lookup, no loop. |
| Salience / working memory | `memory/salience_engine.py`, `memory/working_mem.py` | Scored/updated per request. |
| Emotion engine | `tau/emotion_engine.py` (re-exported as `nature_sci/emotion_engine.py`) | Per-message inference. |
| Tools | `tools/*.py` | Each tool call is one-shot. |
| **Storage** | `storage/neon_store.py` | Resolved below — Neon connects fine per-invocation, with a warm-reused pool. |
| **Vector search** | `memory/sem_retrieval.py` | Resolved below — pgvector query, no local disk involved. |
| **Embeddings** | `storage/embeddings.py` | Resolved below — an HTTP call to Modal, not an in-process model. |
| **Cache** | `cache/*.py`, `cache/ddb_backend.py` | Resolved below — DynamoDB-backed, in-memory L1 for warm invocations. |

**Deploy shape:** FastAPI + Mangum on Lambda, behind a Function URL (not API
Gateway — see `docs/AWS_DEPLOYMENT.md` for why). `main.py`'s lifespan detects
`AWS_LAMBDA_FUNCTION_NAME` and skips starting the KAIROS daemon loop.

---

## Medium — EventBridge-scheduled Lambda (TickFunction)

| Component | File(s) | Why Medium |
|---|---|---|
| KAIROS tick | `tick_handler.py` calling `KairosDaemon.run_once()` | Same decision logic as the daemon, fired every 15 minutes by EventBridge instead of looping with `asyncio.sleep(60)`. Gets you "checks in periodically" without an always-on process. |
| CI/CD (`.github/workflows/semblance.yml`) | Runs on push, lints, tests, deploys, stops. |
| Frontend (`.github/workflows/cloudflare-pages.yml`) | Builds the Vite app and deploys to Cloudflare Pages on push. |

---

## Heavy — not deployed here; documented for later

| Component | File(s) | Why it can't be Light/Medium |
|---|---|---|
| KAIROS daemon (`start()`) | `agents/kairos.py` | The infinite loop specifically — `run_once()` (used by Medium) is the Light/Medium-compatible half of this file. |
| Proactive agent | `agents/proactive.py` | Only meaningful driven by something always-on. |
| UDS inbox | `agents/uds_inbox.py` | Opens a Unix domain socket server — needs a live listener. |
| Bridge agent | `agents/bridge.py` | Holds open a WebSocket/polling connection for remote control. |
| Swarm workers | `agents/swarm.py` | Light if each run is spun up/torn down per request (current assumption); Heavy only if workers must persist across turns. |

**If you want this later:** one small persistent box (EC2/Fargate
`t4g.nano`/`t4g.micro`) running just these four components, calling the
Light Lambda over HTTP for everything else. This is the point where the
budget moves from "~$0" toward the R59 ceiling — budget for it explicitly
rather than letting it happen by accident.

---

## External / Managed — not a tier, just a dependency

| Service | Notes |
|---|---|
| Neon Postgres + pgvector | Free-tier hosted, autosuspends when idle. Replaces Aiven MySQL + ChromaDB — one database instead of two services. |
| Modal | Runs `modal_app/embeddings.py`. Scales to zero; $30/month free credit. |
| Groq | Qwen3.8-27B (chat) + DeepSeek-R1-Distill-70B (planning). Free tier. |
| OpenClaw gateway | Optional. `tools/openclaw_bridge.py` talks to it over HTTP at `OPENCLAW_URL` if you self-host it — a Heavy-tier persistent Node process, entirely separate from this stack. Disabled (fails closed) if `OPENCLAW_URL` is unset. |

---

## Decisions (previously open, now resolved)

1. **Chroma → pgvector.** One Neon database holds both raw memory rows and
   their embeddings, so semantic search is a query against the same table
   pgvector indexes — no separate vector DB, no local disk dependency.
2. **Embeddings → Modal, hosted.** `storage/embeddings.py` calls a Modal HTTP
   endpoint instead of loading `sentence-transformers` in-process. Falls back
   to a deterministic (non-semantic) vector if `MODAL_EMBEDDINGS_URL` is
   unset, so local dev and tests don't need Modal deployed first.
3. **Neon access pattern → per-request, warm-reused pool.**
   `storage/neon_store.get_store()` is a module-level singleton: `connect()`
   is a no-op once the pool exists, so a warm Lambda reuses it and a cold one
   pays the connection cost once.
4. **KAIROS → Medium tier (scheduled), Heavy tier deferred.** The daemon loop
   itself isn't deployed; `run_once()` covers the same decision logic on an
   EventBridge schedule. Full Heavy tier (real-time reactivity, WebSocket
   bridge) stays documented above as explicit future work, not default scope.
