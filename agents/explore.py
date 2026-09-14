import re

from agents.base_agent import BaseAgent


class ExploreAgent(BaseAgent):
    """
    Fast knowledge and codebase search subagent.
    Spawned via AgentTool. Searches web, codebase files, and memory.
    """

    async def run(self, task: dict) -> dict:
        query  = task.get("query", "")
        scope  = task.get("scope", "all")   # all | web | memory | code
        top_k  = task.get("top_k", 5)

        self.log_audit(f"explore:search:{scope}:{query[:60]}")

        results = {}

        if scope in ("all", "web"):
            results["web"] = await self._web_search(query)

        if scope in ("all", "memory"):
            results["memory"] = await self._memory_search(query, top_k)

        if scope in ("all", "code"):
            results["code"] = await self._code_search(query)

        return {
            "query": query,
            "scope": scope,
            "results": results,
        }

    async def _web_search(self, query: str) -> list:
        # Routed through call_tool (Step 5) rather than instantiating
        # SerpTool directly, so this sub-agent's web search is
        # permission-gated and audited like every other tool call.
        result = await self.call_tool("web_search", {"query": query, "num": 5})
        return result if isinstance(result, list) else [result]

    async def _memory_search(self, query: str, top_k: int) -> list[dict]:
        try:
            from memory.sem_retrieval import SEMRetrieval
            return await SEMRetrieval().retrieve(query, top_k=top_k)
        except Exception as e:
            return [{"error": str(e)}]

    async def _code_search(self, query: str) -> list[dict]:
        """Grep-style search through local project files."""
        import os

        matches = []
        search_dirs = [".", "pipeline", "agents", "tools", "memory", "tau", "cache"]
        pattern = re.compile(re.escape(query), re.IGNORECASE)

        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            for fname in os.listdir(d):
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(d, fname)
                try:
                    with open(fpath, "r", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if pattern.search(line):
                                matches.append({
                                    "file": fpath,
                                    "line": i,
                                    "content": line.strip()[:200],
                                })
                                if len(matches) >= 20:
                                    return matches
                except Exception:
                    continue
        return matches
