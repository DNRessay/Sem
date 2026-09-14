from agents.base_agent import BaseAgent

SEMBLANCE_KNOWLEDGE = """
SEMBLANCE v9 — CABLES MAN Architecture

PIPELINE: Bootstrap (7-stage init) → CTX Assembly (SEMBLANCE.md hierarchy, 40k limit)
→ Memory Load (SEM RETRIEVAL cosine + MySQL raw) → Query Engine (14 cache vectors)
→ Tool Execution (BYPASS/ALLOW_EDITS/AUTO) → CTX Pressure (5 compaction strategies)
→ Sub-Agent Delegation (Fork/Teammate/Worktree)

CORE: CABLES MAN orchestrates all agents. Zero direct API calls — all through TOOLS.
NATURE SCI: BERT + RNN + CNN + GAN emotional ensemble. Modulates all responses.
TAU: Adaptive identity engine. PACIFIC OCEAN model (29.25%→76% personalization).
DREAM: Memory consolidation. 3-gate (24hr + 5 sessions + lock). 4 phases. Nothing deleted.

AGENTS: KAIROS (always-on daemon, 15s budget), ULTRAPLAN (GPT-OSS-120B, 30min),
COORDINATOR (XML parallel workers), DREAM, PROACTIVE, EXPLORE, PLAN, GENERAL,
GUIDE, SWARM (async isolated), UDS INBOX, BRIDGE, BUDDY (18 species companion).

TOOLS REGISTRY (flat): MCP, AgentTool, BashTool (23 security checks), ArtifactTool.
Web: SerpAPI, WebFetch, NewsTool. Misc: Calendar, WhatsApp.

STORAGE: Neon Postgres + pgvector — one database holds raw memory rows and their
embeddings side by side, so semantic search is a query against the same table.
CACHE: SysCache (0.10× read, 1.25× write), ConvCache (rolling 20-block), CacheCtrl (14 vectors)
— all DynamoDB-backed with an in-memory L1 layer for warm Lambda invocations.

INFRASTRUCTURE: AWS Lambda + Function URL (FastAPI via Mangum), Groq (Qwen3.8-27B +
GPT-OSS-120B open-weight models), Neon Postgres (free tier), DynamoDB cache (pay-per-request),
Modal (sentence-transformer embeddings, scales to zero) — a few rand a month for one user.
"""


class GuideAgent(BaseAgent):
    """
    Self-knowledge agent.
    Answers questions about Semblance's own capabilities and current state.
    """

    async def run(self, task: dict) -> dict:
        query   = task.get("query", "").lower()
        context = task.get("runtime_context", {})

        self.log_audit(f"guide:query:{query[:60]}")

        answer = self._answer(query, context)
        return {"query": query, "answer": answer}

    def _answer(self, query: str, ctx: dict) -> str:
        if not query:
            return SEMBLANCE_KNOWLEDGE.strip()

        sections = {
            "agent":      self._section("AGENTS"),
            "tool":       self._section("TOOLS"),
            "pipeline":   self._section("PIPELINE"),
            "memory":     self._section("STORAGE") + "\n" + self._section("CACHE"),
            "cache":      self._section("CACHE"),
            "tau":        self._section("TAU"),
            "dream":      self._section("DREAM"),
            "emotion":    self._section("NATURE SCI"),
            "infra":      self._section("INFRASTRUCTURE"),
        }

        for keyword, section in sections.items():
            if keyword in query:
                return section

        return (
            f"I couldn't find a specific answer for '{query}' in my self-knowledge.\n\n"
            f"Here's a full overview:\n\n{SEMBLANCE_KNOWLEDGE.strip()}"
        )

    def _section(self, heading: str) -> str:
        lines = SEMBLANCE_KNOWLEDGE.splitlines()
        result = []
        capturing = False
        for line in lines:
            if heading in line:
                capturing = True
            if capturing:
                result.append(line)
                if result and line.strip() == "" and len(result) > 2:
                    break
        return "\n".join(result).strip() or SEMBLANCE_KNOWLEDGE.strip()
