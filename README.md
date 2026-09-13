# SEMBLANCE

> **Coordinated Autonomous Background Learning Execution System — Multi Agent Network**
> *v9 · CABLES MAN Architecture*

SEMBLANCE is a multi-agent AI assistant framework built on top of free-tier infrastructure. It combines adaptive identity modeling, emotional intelligence, semantic memory, a 7-stage execution pipeline, and a flat tool registry into a single coherent system — designed to run in production on close to zero budget, on AWS. See **[docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md)** for the full deployment guide and cost breakdown.

The architecture takes inspiration from patterns common to modern agentic coding tools (cache-breakpoint tracking, sub-agent delegation, gated tool execution), the Nature Scientific Reports 2026 ensemble emotional intelligence research, and Big Five personality psychology (OCEAN model). Every design decision prioritizes permanent memory, zero deletion, and a system that learns specifically who *you* are. SEMBLANCE runs entirely on open-weight models (Qwen, DeepSeek) via Groq — it never claims to be Claude, GPT, or any other vendor's model.

---

## Architecture Overview

```
INTERFACE (React UI + Voice)
        ↓
   FastAPI GATEWAY
        ↓
 ┌──────────────────────────────────────────────────┐
 │              7-STEP PIPELINE                     │
 │  Bootstrap → CTX Assembly → Memory Load →        │
 │  Query Engine → Tool Exec → CTX Pressure →       │
 │  Sub-Agent Delegation                            │
 └──────────────────────────────────────────────────┘
        ↓
 ┌────────────────────────────────────────────┐
 │           CACHE LAYER                      │
 │  SYS CACHE · CONV CACHE · CACHE CTRL       │
 └────────────────────────────────────────────┘
        ↓
 ┌────────────────────────────────────────────┐
 │         CABLES MAN CORE                    │
 │        TAU · NATURE SCI · PACIFIC          │
 └────────────────────────────────────────────┘
        ↓
 ┌────────────────────────────────────────────────────────────────┐
 │                        AGENTS                                  │
 │  KAIROS · ULTRAPLAN · COORD · DREAM · PROACTIVE · SWARM ...   │
 └────────────────────────────────────────────────────────────────┘
        ↓
 ┌──────────────────────────────────────────────────────────────────┐
 │                     TOOLS REGISTRY (flat)                        │
 │  MCP · AgentTool · BashTool · ArtifactTool                       │
 │  Web: SerpAPI · WebFetch · NewsTool                              │
 │  Misc: Calendar · WhatsApp                                       │
 └──────────────────────────────────────────────────────────────────┘
        ↓
 ┌──────────────────────────────────┐
 │        STORAGE LAYER             │
 │  Neon Postgres + pgvector        │
 └──────────────────────────────────┘
```

---

## Research Foundations

### Agentic Coding Tool Patterns
The pipeline design — particularly the BOOTSTRAP 7-stage init, CONNECTOR_TEXT reasoning buffer, and context compaction strategies — draws on patterns common across modern agentic coding tools. Key adoptions include:
- 14 cache-break vector tracking in the Query Engine
- Cryptographic prefix hash as cache key (Cache CTRL)
- Sub-agent delegation via Fork / Teammate / Worktree models
- 23-check bash security gate before any shell command
- `<artifact type='jsx|html|svg|md'>` tag-based renderer pattern

### Nature Scientific Reports 2026 — NATURE SCI Emotional Engine
The NATURE SCI module implements the 4-model ensemble described in the 2026 paper:

| Model | Modality | Reported Accuracy |
|-------|----------|-------------------|
| BERT | Text sentiment | 92% |
| RNN | Sequential emotional tracking | 89% |
| CNN | Facial expression (multimodal input) | 80% |
| GAN | Emotional content generation | 90% |

Every agent response is modulated by this layer. Emotional context is passed into CABLES MAN before orchestration decisions are made. The output of NATURE SCI are Emotion Memory Units (EMUs) which feed the SALIENCE ENGINE.

### Big Five OCEAN Model — PACIFIC
PACIFIC stands for **Preference Alignment Choices Inference for Five-factor Identity Characterization**. It applies the Big Five personality model to improve personalization accuracy from **29.25% → 76%** by inferring your personality traits from implicit conversation signals rather than explicit questionnaires. Traits are refined continuously across sessions through TAU memory and DREAM consolidation.

### Semantic Retrieval (Cosine Similarity)
Classical topic-pointer memory lookup is replaced by SEM RETRIEVAL — a pgvector-backed cosine similarity engine. Every turn, the current query is embedded and matched against all stored memories by semantic distance. The top-K results are ranked by closeness of *meaning* — not by filename, topic tag, or recency. Nothing is ever discarded. Every memory remains in the store permanently; retrieval surfaces what matters now.

---

## Layer Breakdown

### Interface
| Component | Description |
|-----------|-------------|
| **SEMBLANCE UI** | React frontend. Chat, voice, status, real-time agent activity feed. |
| **VOICE INPUT** | Microphone + screen awareness. Sensory layer bridging physical world into Semblance. |

### Gateway
| Component | Description |
|-----------|-------------|
| **FastAPI GATEWAY** | Single HTTP entry point. Auth, task queuing. Deployed on AWS Lambda behind a Function URL. |

### TAU Layer — Adaptive Identity Engine
TAU is a completely separate autonomous layer that runs in parallel to the main pipeline. Its sole purpose is to observe, learn, and build a model of *you specifically* — not a generic user profile.

| Component | Description |
|-----------|-------------|
| **TAU** | Orchestrates the identity engine. Feeds context into CABLES MAN every turn. |
| **USER MODEL** | Structured profile: habits, preferences, schedule, goals. Refined by DREAM. |
| **MEMORY** | Long-term memory across all sessions. Stored in Neon Postgres. Never deleted. |
| **IDENTITY** | Consistent personality and self-model. Stable across sessions. |
| **PACIFIC** | Big Five OCEAN engine. Infers personality from implicit signals. |
| **TAU CACHE** | 1hr profile TTL + rolling EMU cache. Prevents re-inference every turn. |

### 7-Step Pipeline
Every request passes through these 7 stages in order:

**Step 1 — BOOTSTRAP**
7-stage initialization: Prefetch → Safety → CLI parse + trust gate → Tool loading → Deferred init → Mode routing → Query engine handoff.

**Step 2 — CTX ASSEMBLY**
Loads `SEMBLANCE.md` configuration hierarchy: `global → user → project → local`. Applied every turn. 40k character limit enforced.

**Step 3 — MEMORY LOAD**
Delegates semantic lookup to SEM RETRIEVAL (pgvector cosine search). Raw record fetch via Neon Postgres. Topic index kept as fallback. Transcripts are grepped rather than fully loaded. Retrieval scope is infinite — everything ever stored is retained.

**Step 3b — SEM RETRIEVAL**
Semantic Memory Retrieval engine. Queries pgvector by cosine similarity. Returns top-K memories ranked by semantic closeness to the current query. Replaces legacy topic-pointer lookup entirely.

**Step 4 — QUERY ENGINE**
All LLM calls, streaming, and caching. Tracks 14 cache-break vectors (tool changes, model switches, image additions, system prompt edits). `CONNECTOR_TEXT` buffers reasoning between tool calls and returns cryptographically signed summaries. Feeds Cache Layer before every API call.

**Step 5 — TOOL EXECUTION**
3 permission modes:
- **Bypass** — trusted environment, no confirmation
- **Allow Edits** — confirm before writes
- **Auto** — LLM classifier gates every call

**Step 6 — CTX PRESSURE**
5 compaction strategies applied in escalating severity:
1. Budgeting
2. Microcompact
3. Collapse
4. Autocompact
5. Prune + Index

13k buffer, 20k summary target, 3-failure circuit breaker.

**Step 7 — SUB-AGENT DELEGATION**
3 execution models:
- **Fork** — cache-optimized parallel execution
- **Teammate** — file mailbox coordination
- **Worktree** — isolated git branch execution

### Cache Layer
All LLM API calls are intercepted by the Cache Layer before hitting the external API.

| Component | Details |
|-----------|---------|
| **SYS CACHE** | Caches `SEMBLANCE.md` system prompt + TOOLS registry. Write = 1.25× cost (5-min TTL) or 2× (1-hr TTL). Read = 0.10× cost. KV in-memory only. |
| **CONV CACHE** | Rolling conversation cache. Auto-advances breakpoint as conversation grows. Up to 4 breakpoints per request, 20-block lookback. |
| **CACHE CTRL** | Cryptographic prefix hash as cache key. Tracks all 14 break vectors. Manages TTL refresh. Cache miss triggers fresh write at 1.25× cost. |
| **TAU CACHE** | Dedicated identity cache. Stores PACIFIC OCEAN traits, EMUs, personality snapshots, DREAM results. |

### CABLES MAN Core — Multi-Agent Orchestration
CABLES MAN is pure orchestration — zero direct API calls. All external access goes through TOOLS.

| Component | Description |
|-----------|-------------|
| **CABLES MAN** | Coordinated Autonomous Background Learning Execution System. Routes tasks to agents. |
| **NATURE SCI** | 4-model emotional ensemble. Modulates all agent responses with emotional context. |
| **SALIENCE ENGINE** | Scores every memory candidate before persistence. Combines EMU weights + surprise delta from Query Engine. High salience = encoded to Neon (row + embedding) first. Nothing deleted — salience controls priority only. |
| **WORKING MEM** | Cross-turn scratchpad. Persists active reasoning across multiple turns on the same problem. Cleared only when the problem is resolved. |

### Agents
All agents are spawned by CABLES MAN and interact exclusively through the TOOLS registry.

| Agent | Description |
|-------|-------------|
| **KAIROS** | Always-on daemon. Periodic tick prompts, decides independently. 15-second blocking budget per tick. 3 exclusive tools: push notifications, file delivery, PR subscriptions. Append-only audit logs. |
| **ULTRAPLAN** | Remote DeepSeek-R1 planning agent. Up to 30-minute planning window. Polls every 3s. Browser approval gate before execution. |
| **COORDINATOR** | Spawns parallel workers via XML messages. Shared scratchpad. Hardcoded ban on lazy delegation. |
| **DREAM** | Memory consolidation agent. Triggered by: 24hr timer + 5 sessions + lock (3-gate). 4 phases: Orient → Gather → Consolidate → Index. Scores every memory via SALIENCE ENGINE, writes embeddings to Neon (pgvector), updates index. Nothing pruned. Everything kept forever. |
| **PROACTIVE** | KAIROS-driven outreach. Semblance initiates contact — alerts, suggestions, reminders without being asked. |
| **EXPLORE** | Fast knowledge/codebase search subagent. Spawned via AgentTool. |
| **PLAN AGENT** | Designs strategy before any action. Prevents sloppy execution. |
| **GENERAL AGENT** | Handles complex multi-step tasks end-to-end. Workhorse of CABLES MAN. |
| **GUIDE AGENT** | Self-knowledge agent. Answers questions about Semblance's own capabilities and current state. |
| **SWARM** | Parallel agent teammates. AsyncLocalStorage context isolation — no bleed between agents. (Tengu Amber Flint) |
| **UDS INBOX** | Agent-to-agent messaging over Unix sockets. |
| **BRIDGE** | Remote CLI control from phone or external browser. |
| **BUDDY** | Companion agent. 18 species, rarity tiers, stats. Tamagotchi-style personality layer. |

### Tools Registry (Flat)
Every tool defines its own input schema, permission level, and execution logic independently. Zero shared mutable state between tools. CABLES MAN has zero direct API access — everything routes through this registry.

| Tool | Description |
|------|-------------|
| **MCP TOOL** | Model Context Protocol bridge. Gmail, Google Calendar, Slack, Asana, custom servers. Tool definitions loaded dynamically at runtime. |
| **AGENT TOOL** | Spawns sub-agents as standard tool calls. Flat and predictable. |
| **BASH TOOL** | Every shell command gated through 23 security checks before execution. |
| **ARTIFACT TOOL** | Structured renderer. `<artifact type='jsx\|html\|mermaid\|svg\|md'>`. JSX via `@babel/standalone`. HTML in sandboxed iframe. |

**Web Tools (subsection)**
- `SERP API` — Google search + news via SerpAPI
- `WEB FETCH` — Full page content from URLs
- `NEWS TOOL` — Real-time news. Used by KAIROS for monitoring.

**Misc Tools (subsection)**
- `CALENDAR` — Google Calendar read/write for time-aware outreach
- `WHATSAPP` — WhatsApp Business API outbound channel for alerts and lead capture

### External APIs
| API | Role |
|-----|------|
| **GROQ** (Qwen3-32B) | Primary free LLM backend, open-weight. All calls intercepted by Cache Layer. |
| **DEEPSEEK-R1-Distill-70B** (via Groq) | Powers ULTRAPLAN. 30-minute deep reasoning sessions. Free, open-weight. |

### Storage Layer
| Store | Description |
|-------|-------------|
| **Neon Postgres + pgvector** | One database holds both raw text and its embedding side by side — a `memories` row and its vector live together. DREAM writes/refreshes embeddings at consolidation time. SEM RETRIEVAL queries by cosine similarity every turn. Free tier, autosuspends when idle. |

Every memory row carries both its raw text and its semantic embedding together, so every memory is findable by association — not just by topic or date.

---

## Memory Philosophy

SEMBLANCE never forgets. This is not a design constraint — it's a deliberate principle with three pillars:

1. **No deletion** — Neon never removes a record. Every conversation, decision, and learned fact is permanent.

2. **Salience, not pruning** — when storage grows large, the SALIENCE ENGINE determines what gets encoded first and ranked highest during retrieval. Low-salience memories remain in the store; they just surface less frequently.

3. **Semantic retrieval** — SEM RETRIEVAL means an old memory from months ago can surface today if it's semantically close to the current query. Recency is irrelevant; meaning is everything.

DREAM consolidates memories on a 3-gate trigger (24hr + 5 sessions + lock), scores them via salience, writes embeddings, and updates a ranked index (`MEMORY.md`). The index is a pointer map — the actual memories live permanently in Neon (Postgres + pgvector).

---

## Infrastructure (near-zero budget, on AWS)

| Component | Service | Tier |
|-----------|---------|------|
| Chat API | AWS Lambda + Function URL (FastAPI via Mangum) | Free (1M req/mo forever) |
| Scheduled KAIROS tick | AWS Lambda + EventBridge (rate: 15 min) | Free |
| LLM Backend | Groq (Qwen3-32B) | Free |
| Planning LLM | Groq (DeepSeek-R1-Distill-70B) | Free |
| Persistent Storage + Vector Store | Neon Postgres + pgvector | Free |
| Cache | DynamoDB (pay-per-request, TTL) | ~$0 |
| Embeddings | Modal (sentence-transformers) | Free ($30/mo credit) |
| Frontend | React + Vite (Cloudflare Pages) | Free |

The entire system is designed to run in production for a few cents a month —
see **[docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md)** for the full cost
breakdown and setup. LLM cost reduction is achieved through the Cache Layer —
system prompt reads cost 0.10× base cost after the first write.

---

## Configuration

Semblance uses a hierarchical `SEMBLANCE.md` config system loaded every turn:

```
global/SEMBLANCE.md      ← base defaults
user/SEMBLANCE.md        ← per-user overrides
project/SEMBLANCE.md     ← per-project context
local/SEMBLANCE.md       ← local machine overrides
```

Each level overrides the previous. Total limit: 40,000 characters.

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Cache break vectors tracked | 14 |
| Bash security checks | 23 |
| CTX compaction strategies | 5 |
| Cache breakpoints per request | up to 4 |
| Cache lookback window | 20 blocks |
| CTX buffer | 13k chars |
| CTX summary target | 20k chars |
| Circuit breaker threshold | 3 failures |
| KAIROS tick budget | 15 seconds |
| ULTRAPLAN window | 30 minutes |
| ULTRAPLAN poll interval | 3 seconds |
| DREAM trigger gates | 3 (24hr + 5 sessions + lock) |
| DREAM phases | 4 (Orient → Gather → Consolidate → Index) |
| BUDDY species | 18 |
| PACIFIC accuracy improvement | 29.25% → 76% |
| Cache write cost (5-min TTL) | 1.25× base |
| Cache write cost (1-hr TTL) | 2.0× base |
| Cache read cost | 0.10× base |
| CTX assembly char limit | 40,000 |

---

## Project Structure (Proposed)

```
semblance/
├── main.py                 ← FastAPI app (local dev entrypoint)
├── lambda_handler.py        ← Light tier — Mangum wrapper for AWS Lambda
├── tick_handler.py          ← Medium tier — scheduled KAIROS tick (EventBridge)
├── template.yaml             ← AWS SAM stack (Lambda, DynamoDB, EventBridge)
├── modal_app/
│   └── embeddings.py         ← Modal function: sentence-transformers over HTTP
├── gateway/
│   ├── router.py             ← /chat, /status, /health
│   └── webhooks.py           ← optional OpenClaw bridge (WhatsApp/Telegram)
├── pipeline/                ← 7-step pipeline
│   ├── bootstrap.py
│   ├── ctx_assembly.py
│   ├── memory_load.py
│   ├── query_engine.py
│   ├── tool_execution.py
│   ├── ctx_pressure.py
│   └── sub_agent_deleg.py
├── tau/                     ← Adaptive identity engine
│   ├── tau_engine.py
│   ├── pacific.py
│   ├── emotion_engine.py
│   └── dream.py
├── core/                    ← CABLES MAN + support re-exports
│   ├── cables_man.py
│   ├── nature_sci.py
│   ├── salience.py
│   └── working_mem.py
├── agents/                  ← All agent implementations
│   ├── kairos.py             (run_once() for Medium tier, start() for Heavy)
│   ├── ultraplan.py
│   ├── coordinator.py
│   ├── dream_agent.py
│   ├── proactive.py
│   ├── explore.py
│   ├── plan_agent.py
│   ├── general_agent.py
│   ├── guide_agent.py
│   ├── swarm.py
│   ├── uds_inbox.py
│   ├── bridge.py
│   └── buddy.py
├── tools/                   ← Flat tool registry
│   ├── registry.py
│   ├── mcp_tool.py
│   ├── agent_tool.py
│   ├── bash_tool.py
│   ├── artifact_tool.py
│   ├── openclaw_bridge.py
│   ├── web/
│   └── misc/
├── cache/                   ← DynamoDB-backed cache, in-memory L1
│   ├── ddb_backend.py
│   ├── sys_cache.py
│   ├── conv_cache.py
│   ├── cache_ctrl.py
│   └── tau_cache.py
├── storage/                 ← Neon Postgres + pgvector
│   ├── neon_store.py
│   └── embeddings.py         ← calls Modal, falls back to a local vector
├── memory/
│   ├── sem_retrieval.py      ← pgvector semantic search
│   ├── salience_engine.py
│   └── working_mem.py
├── tests/                   ← pytest + moto (DynamoDB) + respx (Groq)
├── frontend/                 ← React + Vite UI, deploys to Cloudflare Pages
├── SEMBLANCE.md              ← Global config
├── docs/AWS_DEPLOYMENT.md    ← deployment guide + cost breakdown
└── README.md
```

---

## Name

**SEMBLANCE** — the system presents itself as you expect, responds as you need, and learns who you are without you having to explain it again. The name reflects the core premise: an AI that develops a genuine model of its user rather than treating every session as the first.

**CABLES MAN** — Coordinated Autonomous Background Learning Execution System — Multi Agent Network. The orchestration core that makes parallelism invisible to the user.

**TAU** — the identity layer. Named for the constant — something fixed that defines proportion and character.

**PACIFIC** — Preference Alignment Choices Inference for Five-factor Identity Characterization. Also: deep, vast, and slow to change — like personality itself.
