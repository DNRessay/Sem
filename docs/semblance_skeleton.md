# SEMBLANCE — Skeleton Codebase (historical planning doc)
> High-level structure only. Classes, functions, docstrings, and build steps.
> Stack as originally planned: FastAPI · Python 3.11 · ChromaDB · Aiven MySQL · React · Groq API
>
> **Superseded** — the actual deployment moved to AWS Lambda + Neon (Postgres/pgvector)
> + DynamoDB + Modal; see `docs/AWS_DEPLOYMENT.md` and `SEMBLANCE-TIERS.md` for what's
> actually live. UNDERCOVER/SHADOW TOOL, mentioned below as originally planned, were
> never built for the AWS deployment and should not be added — see `docs/AWS_DEPLOYMENT.md`
> for why.

---

## PROJECT STRUCTURE

```
semblance/
├── main.py                  # FastAPI entry point
├── config.py                # Env vars, constants
├── gateway/
│   └── router.py            # HTTP routes + auth
├── tau/
│   ├── tau_engine.py        # TAU adaptive identity
│   ├── pacific.py           # OCEAN personality model
│   ├── dream.py             # Memory consolidation agent
│   └── tau_cache.py         # TAU-specific cache
├── pipeline/
│   ├── bootstrap.py         # Step 1 — 7-stage init
│   ├── ctx_assembly.py      # Step 2 — SEMBLANCE.md loader
│   ├── memory_load.py       # Step 3 — memory coordinator
│   ├── query_engine.py      # Step 4 — LLM calls + cache
│   ├── tool_execution.py    # Step 5 — permission modes
│   ├── ctx_pressure.py      # Step 6 — compaction
│   └── sub_agent_deleg.py   # Step 7 — fork/teammate/worktree
├── cache/
│   ├── sys_cache.py         # System prompt cache
│   ├── conv_cache.py        # Conversation rolling cache
│   └── cache_ctrl.py        # Hash tracker + TTL manager
├── memory/
│   ├── sem_retrieval.py     # ChromaDB cosine search
│   ├── salience_engine.py   # Memory scoring
│   └── working_mem.py       # Cross-turn scratchpad
├── agents/
│   ├── base_agent.py        # Abstract agent base
│   ├── kairos.py            # Always-on daemon
│   ├── ultraplan.py         # GPT-OSS-120B planner
│   ├── coordinator.py       # XML parallel workers
│   ├── dream_agent.py       # 4-phase consolidation
│   ├── proactive.py         # KAIROS-driven outreach
│   ├── swarm.py             # Parallel async agents
│   └── buddy.py             # Companion agent
├── tools/
│   ├── registry.py          # Flat tool registry
│   ├── agent_tool.py        # Sub-agent spawner
│   ├── bash_tool.py         # Shell + 23 security checks
│   ├── mcp_tool.py          # MCP bridge
│   ├── artifact_tool.py     # JSX/HTML/SVG renderer
│   ├── web/
│   │   ├── serp_tool.py     # SerpAPI search
│   │   ├── fetch_tool.py    # URL retrieval
│   │   └── news_tool.py     # Real-time news
│   └── misc/
│       ├── calendar_tool.py # Google Calendar
│       └── whatsapp_tool.py # WhatsApp Business API
├── storage/
│   ├── mysql_store.py       # Aiven MySQL ORM
│   └── chroma_store.py      # ChromaDB vector store
├── nature_sci/
│   └── emotion_engine.py    # BERT + RNN + CNN ensemble
├── undercover/
│   ├── undercover.py        # Stealth mode controller
│   └── shadow_tool.py       # Identity masking tool
└── frontend/
    └── src/
        ├── App.jsx
        ├── components/
        │   ├── ChatWindow.jsx
        │   ├── VoiceInput.jsx
        │   ├── AgentFeed.jsx
        │   └── StatusBar.jsx
        └── hooks/
            └── useStream.js
```

---

## LAYER 1 — ENTRY POINT

### `main.py`
```python
from fastapi import FastAPI
from gateway.router import router
from agents.kairos import KairosDaemon
from storage.mysql_store import MySQLStore
from storage.chroma_store import ChromaStore

app = FastAPI(title="Semblance")

def create_app() -> FastAPI:
    """
    Bootstrap the FastAPI application.
    - Register all routers
    - Connect to Aiven MySQL and ChromaDB
    - Start KAIROS daemon as background task
    - Return configured app instance
    """

@app.on_event("startup")
async def startup():
    """
    Run on server start:
    1. Init MySQL connection pool
    2. Init ChromaDB client
    3. Load SEMBLANCE.md hierarchy into memory
    4. Start KairosDaemon background task
    5. Warm sys cache with TOOLS registry + system prompt
    """

@app.on_event("shutdown")
async def shutdown():
    """
    Graceful shutdown:
    - Flush working memory to MySQL
    - Close DB connections
    - Signal KAIROS to stop after current tick
    """
```

---

## LAYER 2 — GATEWAY

### `gateway/router.py`
```python
from fastapi import APIRouter, Request, Depends
from pipeline.bootstrap import Bootstrap

router = APIRouter()

class GatewayRouter:
    """
    Single HTTP entry point for all Semblance requests.
    Handles: auth, task queuing, response streaming to UI.
    """

    def authenticate(self, request: Request) -> bool:
        """
        Validate API key or session token.
        Assign trust level: TRUSTED | ALLOW_EDITS | AUTO
        Return trust context for pipeline use.
        """

    def queue_task(self, task: dict) -> str:
        """
        Add incoming task to async queue.
        Return task_id for status polling.
        """

    async def stream_response(self, task_id: str):
        """
        SSE stream. Yield pipeline output chunks
        back to the React frontend in real time.
        """

@router.post("/chat")
async def chat_endpoint(request: Request):
    """
    Main chat route.
    1. Authenticate request
    2. Queue task
    3. Hand off to Bootstrap pipeline
    4. Stream response
    """

@router.get("/status/{task_id}")
async def status_endpoint(task_id: str):
    """Return current status of a queued task."""
```

---

## LAYER 3 — TAU ENGINE

### `tau/tau_engine.py`
```python
class TAUEngine:
    """
    Adaptive Identity Engine.
    Runs in parallel with main pipeline.
    Observes every turn, builds a model of the specific user.
    Feeds personalized context into CABLES MAN each turn.
    """

    def observe(self, turn: dict) -> None:
        """
        Process a single conversation turn.
        Extract signals: tone, topic, preference, emotion.
        Update user model incrementally.
        """

    def get_context_injection(self) -> str:
        """
        Return TAU context string to prepend to CABLES MAN prompt.
        Includes: user traits, active EMUs, PACIFIC scores.
        """

    def trigger_dream_if_ready(self) -> bool:
        """
        Check 3-gate: 24hr elapsed + 5 sessions + no lock.
        If all pass, signal DREAM agent to consolidate.
        """
```

### `tau/pacific.py`
```python
class PACIFICEngine:
    """
    Preference Alignment Choices Inference for Five-factor Identity Characterization.
    Big Five (OCEAN) model derived from implicit conversation signals.
    Improves personalization from 29.25% to 76% accuracy.
    """

    def infer_traits(self, conversation_history: list) -> dict:
        """
        Analyse conversation history.
        Return OCEAN scores: O, C, E, A, N (0.0–1.0 each).
        Use lightweight classifier — no external API call.
        """

    def update_profile(self, new_signals: dict) -> None:
        """
        Merge new signals into existing OCEAN profile.
        Write updated profile to TAU cache.
        """

    def get_personalization_vector(self) -> list[float]:
        """
        Return current OCEAN vector for use by CABLES MAN
        when selecting response tone and depth.
        """
```

### `tau/dream.py`
```python
class DREAMAgent:
    """
    Memory consolidation agent.
    3-gate trigger: 24hr + 5 sessions + lock.
    4 phases: Orient → Gather → Consolidate → Index.
    Nothing pruned — ever.
    """

    def check_gates(self) -> bool:
        """Check all 3 trigger conditions. Return True only if all pass."""

    def phase_orient(self) -> dict:
        """
        Phase 1: Survey current memory state.
        Identify gaps, stale entries, unconsolidated sessions.
        """

    def phase_gather(self) -> list:
        """
        Phase 2: Pull raw session transcripts + MySQL records
        since last consolidation window.
        """

    def phase_consolidate(self, raw_memories: list) -> list:
        """
        Phase 3: Score each memory via SalienceEngine.
        Merge duplicates. Compress verbose entries.
        Never delete — only compress and rank.
        """

    def phase_index(self, consolidated: list) -> None:
        """
        Phase 4: Write embeddings to ChromaDB.
        Update MEMORY.md index file.
        Persist structured records to MySQL.
        Release consolidation lock.
        """
```

---

## LAYER 4 — PIPELINE (7 Steps)

### `pipeline/bootstrap.py`
```python
class Bootstrap:
    """
    Step 1 — 7-Stage Init.
    Entry point for every query after gateway auth.
    """

    def prefetch(self) -> None:
        """Pre-load likely-needed tool definitions and cache entries."""

    def safety_check(self, query: str) -> bool:
        """Run safety classifier. Block or flag harmful inputs."""

    def parse_cli_trust(self, context: dict) -> str:
        """
        Parse CLI flags and trust level from gateway context.
        Return trust mode: BYPASS | ALLOW_EDITS | AUTO
        """

    def load_tools(self) -> None:
        """Load all tools from flat registry into active session."""

    def deferred_init(self) -> None:
        """Lazy-load heavy components (ML models) only if needed this turn."""

    def route_mode(self, query: str) -> str:
        """
        Decide execution mode: chat | agent | voice | artifact.
        Return mode string for downstream steps.
        """

    def handoff_to_query_engine(self, context: dict) -> None:
        """Pass fully prepared context to QueryEngine (Step 4)."""
```

### `pipeline/ctx_assembly.py`
```python
class CTXAssembly:
    """
    Step 2 — Context Assembly.
    Loads SEMBLANCE.md hierarchy every single turn.
    Order: global → user → project → local.
    Hard limit: 40,000 characters.
    """

    def load_hierarchy(self) -> str:
        """
        Walk SEMBLANCE.md file tree.
        Merge all levels respecting precedence.
        Truncate to 40k char limit if exceeded.
        """

    def inject_tau_context(self, tau_context: str) -> str:
        """Append TAU personalisation block to assembled context."""

    def validate_length(self, ctx: str) -> str:
        """Enforce 40k char cap. Log warning if truncation occurs."""
```

### `pipeline/memory_load.py`
```python
class MemoryLoad:
    """
    Step 3 — Memory coordinator.
    Delegates semantic search to SEM RETRIEVAL (ChromaDB cosine).
    Delegates raw records to Aiven MySQL.
    Greps transcripts — never fully loads them.
    Infinite retention policy.
    """

    def coordinate(self, query: str) -> dict:
        """
        Orchestrate memory retrieval:
        1. Semantic search via SEMRetrieval
        2. Raw record fetch via MySQLStore
        3. Transcript grep
        4. Merge and deduplicate results
        """

    def grep_transcripts(self, query: str) -> list:
        """
        Grep local transcript files for relevant lines.
        Never load full transcript into memory.
        """
```

### `pipeline/query_engine.py`
```python
class QueryEngine:
    """
    Step 4 — All LLM calls, streaming, caching.
    Tracks 14 cache-break vectors.
    CONNECTOR_TEXT buffers reasoning between tool calls.
    Feeds Cache Layer before every API call.
    """

    CACHE_BREAK_VECTORS = [
        "tool_change", "model_switch", "image_added", "system_prompt_edit",
        "user_model_update", "trust_level_change", "new_agent_spawned",
        "memory_consolidation", "ctx_length_exceeded", "tool_error",
        "session_restart", "undercover_toggle", "mcp_server_change", "manual_flush"
    ]  # 14 vectors

    def call_llm(self, prompt: str, model: str = "llama-3.3-70b") -> str:
        """
        Make LLM API call via Groq.
        Check cache first. On miss, call API and write to cache.
        Stream tokens back to caller.
        """

    def check_cache_break(self) -> bool:
        """
        Evaluate all 14 vectors.
        Return True if any vector has fired since last cache write.
        """

    def connector_text_buffer(self, reasoning: str) -> str:
        """
        Store intermediate reasoning between tool calls.
        Sign with cryptographic hash for integrity.
        Return signed summary string.
        """

    def feed_cache_layer(self, prompt: str) -> None:
        """Write current prompt prefix to SysCache and ConvCache before API call."""
```

### `pipeline/tool_execution.py`
```python
class ToolExecution:
    """
    Step 5 — Tool execution with 3 permission modes.
    BYPASS: trusted env, no confirmation.
    ALLOW_EDITS: confirm before any write.
    AUTO: LLM classifier gates every call.
    """

    def execute(self, tool_name: str, args: dict, trust_mode: str) -> dict:
        """
        Route tool call through correct permission gate.
        Log all executions to append-only audit log.
        Return tool result or confirmation request.
        """

    def _bypass_execute(self, tool_name: str, args: dict) -> dict:
        """Execute immediately with no confirmation. Trusted envs only."""

    def _allow_edits_execute(self, tool_name: str, args: dict) -> dict:
        """Pause and request user confirmation before any write operation."""

    def _auto_execute(self, tool_name: str, args: dict) -> dict:
        """Run LLM classifier to decide approve/deny. Execute if approved."""
```

### `pipeline/ctx_pressure.py`
```python
class CTXPressure:
    """
    Step 6 — Context compaction. 5 strategies.
    Buffer: 13k chars. Summary target: 20k chars.
    Circuit breaker: 3 consecutive failures → halt.
    """

    def apply(self, ctx: str) -> str:
        """
        Auto-select and apply the appropriate compaction strategy.
        Strategies tried in order until ctx fits budget.
        """

    def budget(self, ctx: str) -> str:
        """Strategy 1: Trim low-priority blocks to hit token budget."""

    def microcompact(self, ctx: str) -> str:
        """Strategy 2: Compress verbose sections in-place."""

    def collapse(self, ctx: str) -> str:
        """Strategy 3: Collapse repeated patterns into single references."""

    def autocompact(self, ctx: str) -> str:
        """Strategy 4: LLM-assisted full context summarization."""

    def prune_and_index(self, ctx: str) -> str:
        """Strategy 5: Remove entries + write index pointers to MEMORY.md."""
```

### `pipeline/sub_agent_deleg.py`
```python
class SubAgentDelegation:
    """
    Step 7 — Sub-agent delegation. 3 execution models.
    """

    def fork(self, task: dict) -> list:
        """
        Fork model: spawn cache-optimised parallel sub-agents.
        Each fork shares the parent cache prefix.
        Collect and merge results.
        """

    def teammate(self, task: dict) -> str:
        """
        Teammate model: coordinate via file mailbox.
        Write task to mailbox file, poll for response.
        Used for longer async coordination.
        """

    def worktree(self, task: dict) -> str:
        """
        Worktree model: create isolated git branch.
        Agent works in branch, merges back on completion.
        Used for code changes.
        """
```

---

## LAYER 5 — CACHE LAYER

### `cache/cache_ctrl.py`
```python
class CacheController:
    """
    Master cache controller.
    Cryptographic prefix hash as cache key.
    Tracks all 14 break vectors.
    Manages TTL refresh across SysCache and ConvCache.
    """

    def compute_prefix_hash(self, prompt_prefix: str) -> str:
        """SHA-256 hash of the current prompt prefix. Used as cache key."""

    def is_cache_valid(self, cache_key: str) -> bool:
        """Check if key exists and TTL has not expired."""

    def invalidate(self, reason: str) -> None:
        """
        Invalidate cache for given break vector reason.
        Log invalidation event with timestamp.
        """

    def refresh_ttl(self, cache_key: str) -> None:
        """Reset TTL on active cache entry to prevent premature expiry."""
```

---

## LAYER 6 — MEMORY

### `memory/sem_retrieval.py`
```python
class SEMRetrieval:
    """
    Semantic Memory Retrieval.
    Queries ChromaDB by cosine similarity.
    Returns top-K relevant memories ranked by semantic closeness.
    Nothing discarded.
    """

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Embed query string.
        Run cosine similarity search against ChromaDB.
        Return top_k results with scores and metadata.
        """

    def embed(self, text: str) -> list[float]:
        """Convert text to embedding vector using local model."""
```

### `memory/salience_engine.py`
```python
class SalienceEngine:
    """
    Scores every memory candidate before persistence.
    Combines NATURE SCI EMU weights + surprise delta from QueryEngine.
    High salience = priority encoding to ChromaDB + MySQL.
    Nothing deleted — salience controls priority only.
    """

    def score(self, memory: dict, emu_weights: dict, surprise_delta: float) -> float:
        """
        Compute salience score 0.0–1.0.
        Formula: weighted combination of EMU weight + surprise + recency.
        """

    def rank(self, memories: list[dict]) -> list[dict]:
        """Sort memories by salience score descending."""
```

---

## LAYER 7 — AGENTS

### `agents/base_agent.py`
```python
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    """
    Abstract base for all Semblance agents.
    All agents access external resources exclusively through TOOLS.
    Zero direct API calls permitted.
    """

    def __init__(self, tools_registry, cables_man_ref):
        """
        Inject tool registry and CABLES MAN reference.
        Never store API keys directly.
        """

    @abstractmethod
    def run(self, task: dict) -> dict:
        """Execute the agent's primary task. Must be implemented."""

    def call_tool(self, tool_name: str, args: dict) -> dict:
        """
        All tool calls routed through this method.
        Enforces registry lookup + permission check.
        """

    def log_audit(self, action: str) -> None:
        """Append action to append-only audit log with timestamp."""
```

### `agents/kairos.py`
```python
import asyncio

class KairosDaemon(BaseAgent):
    """
    Always-on background daemon.
    15-second blocking budget per tick.
    3 exclusive tools: push notifications, file delivery, PR subscriptions.
    Append-only audit logs.
    """

    EXCLUSIVE_TOOLS = ["push_notification", "file_delivery", "pr_subscription"]
    TICK_BUDGET_SECONDS = 15

    async def start(self) -> None:
        """Start infinite tick loop as asyncio background task."""

    async def tick(self) -> None:
        """
        Single daemon tick:
        1. Evaluate current context (time, user state, pending alerts)
        2. Decide independently whether to act
        3. If acting, select from EXCLUSIVE_TOOLS only
        4. Execute within 15s budget
        5. Log to audit trail
        """

    def stop(self) -> None:
        """Signal daemon to stop after current tick completes."""
```

### `agents/swarm.py`
```python
from contextvars import ContextVar

class SwarmAgent(BaseAgent):
    """
    Tengu Amber Flint.
    Parallel agent teammates with AsyncLocalStorage-style context isolation.
    No context bleed between concurrent agents.
    """

    _agent_context: ContextVar = ContextVar("agent_context")

    def spawn_parallel(self, tasks: list[dict]) -> list:
        """
        Spawn multiple agents concurrently.
        Each agent gets isolated context via ContextVar.
        Collect results when all complete.
        """

    def isolate_context(self, agent_id: str, context: dict) -> None:
        """Bind context to this async execution context only."""
```

---

## LAYER 8 — TOOLS REGISTRY

### `tools/registry.py`
```python
class ToolsRegistry:
    """
    Flat tool registry. Single source of truth for all tools.
    Each tool defines its own: input schema, permission level, execution logic.
    Zero shared mutable state between tools.
    """

    def register(self, tool_name: str, handler, schema: dict, permission: str) -> None:
        """
        Register a tool.
        permission: BYPASS | ALLOW_EDITS | AUTO
        """

    def get(self, tool_name: str) -> dict:
        """Retrieve tool definition by name. Raise if not found."""

    def list_all(self) -> list[str]:
        """Return names of all registered tools."""

    def load_mcp_tools(self, mcp_server_url: str) -> None:
        """
        Dynamically fetch and register tools from an MCP server at runtime.
        Called during Bootstrap step 1.
        """
```

### `tools/bash_tool.py`
```python
class BashTool:
    """
    Shell command executor.
    Every command passes through 23 security checks before execution.
    """

    SECURITY_CHECKS = [
        "no_rm_rf", "no_fork_bomb", "no_curl_pipe_sh", "no_sudo",
        "no_passwd_access", "no_env_exfil", "no_network_in_bypass_mode",
        "no_write_outside_workspace", "no_kill_signals", "no_cron_edit",
        # ... 13 more
    ]  # 23 total

    def execute(self, command: str, trust_mode: str) -> dict:
        """
        1. Run all 23 security checks
        2. Block if any check fails
        3. Execute in subprocess if all pass
        4. Return stdout, stderr, exit code
        """

    def _run_security_checks(self, command: str) -> list[str]:
        """
        Run all 23 checks against command string.
        Return list of failed check names (empty = all passed).
        """
```

---

## LAYER 9 — STORAGE

### `storage/mysql_store.py`
```python
class MySQLStore:
    """
    Aiven MySQL persistent storage.
    Stores: TAU memory, conversation history, user model, raw memory records.
    Nothing ever deleted — soft-delete only via salience flags.
    """

    def connect(self, connection_string: str) -> None:
        """Open connection pool to Aiven MySQL."""

    def save_memory(self, memory: dict) -> int:
        """Insert memory record. Return new row ID."""

    def get_memories(self, user_id: str, limit: int = 50) -> list[dict]:
        """Fetch most recent memories for user ordered by salience desc."""

    def save_conversation_turn(self, turn: dict) -> None:
        """Persist a single conversation turn with timestamp."""

    def save_user_model(self, user_id: str, model: dict) -> None:
        """Upsert user model (TAU profile + PACIFIC scores)."""
```

### `storage/chroma_store.py`
```python
class ChromaStore:
    """
    Local ChromaDB vector store.
    Holds embeddings alongside MySQL raw text.
    DREAM writes at consolidation time.
    SEM RETRIEVAL queries every turn.
    """

    def init_collection(self, name: str = "semblance_memory") -> None:
        """Create or load ChromaDB collection."""

    def upsert(self, doc_id: str, embedding: list[float], metadata: dict) -> None:
        """Insert or update a document embedding."""

    def query(self, embedding: list[float], top_k: int = 5) -> list[dict]:
        """Cosine similarity search. Return top_k results with distances."""
```

---

## LAYER 10 — NATURE SCI (Emotion Engine)

### `nature_sci/emotion_engine.py`
```python
class NatureSCIEngine:
    """
    Multimodal Emotional Intelligence ensemble.
    BERT (92% text sentiment) + RNN (89% sequential tracking)
    + CNN (80% facial) + GAN (90% emotional content generation).
    Modulates all agent responses.
    Nature Scientific Reports 2026.
    """

    def analyse_text(self, text: str) -> dict:
        """BERT inference. Return emotion label + confidence scores."""

    def track_sequence(self, history: list[dict]) -> dict:
        """RNN tracking of emotional arc across conversation turns."""

    def analyse_facial(self, image_bytes: bytes) -> dict:
        """CNN facial expression classifier. Return dominant emotion."""

    def generate_emotional_content(self, target_emotion: str, prompt: str) -> str:
        """GAN-guided response generation tuned to target emotional register."""

    def get_emu_weights(self) -> dict:
        """
        Return current Emotion Memory Unit weights.
        Used by SalienceEngine for memory scoring.
        """
```

---

## LAYER 11 — FRONTEND (React)

### `frontend/src/hooks/useStream.js`
```javascript
/**
 * useStream — SSE hook for real-time response streaming.
 * Connects to /chat SSE endpoint.
 * Yields tokens to ChatWindow as they arrive.
 * Handles reconnection on drop.
 */
export function useStream(taskId) { }
```

### `frontend/src/components/ChatWindow.jsx`
```jsx
/**
 * ChatWindow — Primary conversation UI.
 * Renders streaming token output.
 * Shows agent activity indicators inline.
 * Supports artifact rendering (JSX/HTML/SVG/MD).
 */
export default function ChatWindow() { }
```

### `frontend/src/components/AgentFeed.jsx`
```jsx
/**
 * AgentFeed — Real-time agent activity sidebar.
 * Shows which agents are active, what tools they're calling,
 * and KAIROS tick status.
 * Connects to /status SSE stream.
 */
export default function AgentFeed() { }
```

---

## HOW TO FINISH IT — STEP BY STEP

### Phase 1 — Foundation (Week 1–2)
```
1. Set up repo, venv, install: fastapi uvicorn chromadb
   pymysql sqlalchemy python-dotenv groq httpx

2. Build config.py — load all env vars:
   GROQ_API_KEY, AIVEN_MYSQL_URL, SERP_API_KEY,
   WHATSAPP_TOKEN, GOOGLE_CALENDAR_CREDS

3. Implement MySQLStore + ChromaStore
   → Test: insert a memory, retrieve it, query by vector

4. Implement ToolsRegistry with 3 tools: BashTool, WebFetch, SerpAPI
   → Test: call each tool through registry

5. Stand up FastAPI gateway with one /chat POST route
   → Returns hardcoded string for now
```

### Phase 2 — Pipeline (Week 3–4)
```
6. Implement Bootstrap (Step 1) — just steps 1–4 for now
7. Implement CTXAssembly (Step 2) — load a flat SEMBLANCE.md
8. Implement QueryEngine (Step 4) — real Groq API call
   → /chat now returns a real LLM response

9. Add SEMRetrieval — embed query, query ChromaDB
10. Wire MemoryLoad (Step 3) to use SEMRetrieval
    → Conversation now has memory
```

### Phase 3 — Agents (Week 5–6)
```
11. Implement BaseAgent + one concrete agent (GeneralAgent)
12. Implement CABLES MAN orchestrator shell
    → Routes tasks to GeneralAgent

13. Add KairosDaemon as asyncio background task
    → Logs a tick every 15 seconds to start

14. Implement SalienceEngine + hook into memory writes
15. Implement DREAMAgent — manual trigger first, then auto
```

### Phase 4 — TAU + Emotion (Week 7–8)
```
16. Implement PACIFICEngine — start with rule-based OCEAN scoring
    then replace with BERT classifier

17. Implement TAUEngine — observe() method first
    → Feeds into CTXAssembly context injection

18. Integrate NatureSCIEngine — BERT text sentiment first
    Add RNN sequence tracking next
    CNN facial and GAN generation last (optional for MVP)
```

### Phase 5 — ProductiZation (Week 9–10)
```
19. Add WhatsApp tool — connect Business API
    → KAIROS can now send proactive messages

20. Add Google Calendar tool
21. Build React frontend: ChatWindow + AgentFeed + useStream
22. Add UNDERCOVER mode behind env var flag
23. Deploy to Hetzner CCX23, set up systemd service for uvicorn
24. Add basic auth + rate limiting to gateway
```

### Phase 6 — Money Layer (Week 11–12)
```
25. Add multi-tenant user model to MySQLStore
26. Add Stripe subscription webhook endpoint
27. Rate-limit free vs paid tiers in GatewayRouter
28. Package WhatsApp business assistant as standalone onboarding flow
29. Write SEMBLANCE.md template for new business clients
```

---

## KEY ENV VARS NEEDED

```env
GROQ_API_KEY=
AIVEN_MYSQL_URL=mysql+pymysql://user:pass@host/db
CHROMA_PERSIST_DIR=./data/chroma
SERP_API_KEY=
WHATSAPP_TOKEN=
WHATSAPP_PHONE_ID=
GOOGLE_CALENDAR_CREDS=./creds/google.json
SEMBLANCE_TRUST_MODE=AUTO
UNDERCOVER=false
SECRET_KEY=your-signing-secret
```

---

*Total estimated build time solo: 10–12 weeks to full MVP.*
*With the skeleton above, each file is an isolated unit — you can build and test them independently.*
