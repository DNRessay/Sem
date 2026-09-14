import asyncio
import xml.etree.ElementTree as ET

from agents.base_agent import BaseAgent


class CoordinatorAgent(BaseAgent):
    """
    Spawns parallel workers via XML messages.
    Shared scratchpad for inter-agent communication.
    Hardcoded ban on lazy delegation — every task must be meaningfully assigned.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._scratchpad: dict[str, list[str]] = {}   # task_id -> notes
        self._results: dict[str, dict] = {}

    async def run(self, task: dict) -> dict:
        task_id = task.get("id", "coord_task")
        subtasks = self._parse_xml_subtasks(task.get("xml", ""))
        if not subtasks:
            return {"error": "No valid subtasks found in XML payload"}

        self._scratchpad[task_id] = []
        self.log_audit(f"coordinator:spawning:{len(subtasks)}:workers")

        # Spawn all workers concurrently
        results = await asyncio.gather(*[
            self._execute_worker(task_id, st) for st in subtasks
        ], return_exceptions=True)

        merged = {}
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                merged[f"worker_{i}"] = {"error": str(r)}
            else:
                merged[f"worker_{i}"] = r

        self._results[task_id] = merged
        self.log_audit(f"coordinator:complete:{task_id}")
        return {"task_id": task_id, "results": merged, "scratchpad": self._scratchpad[task_id]}

    def _parse_xml_subtasks(self, xml_str: str) -> list[dict]:
        """Parse XML task definitions into dicts."""
        if not xml_str.strip():
            return []
        try:
            root = ET.fromstring(f"<tasks>{xml_str}</tasks>")
            tasks = []
            for task_el in root.findall("task"):
                tasks.append({
                    "id": task_el.get("id", ""),
                    "type": task_el.get("type", "general"),
                    "query": task_el.findtext("query", ""),
                    "context": task_el.findtext("context", ""),
                })
            return tasks
        except ET.ParseError:
            return []

    async def _execute_worker(self, parent_id: str, subtask: dict) -> dict:
        """Execute a single worker task. No lazy delegation — must do real work."""
        query = subtask.get("query", "")
        task_type = subtask.get("type", "general")

        # Anti-lazy-delegation: reject empty or pass-through tasks
        if not query or query.lower() in ("delegate", "pass", "forward"):
            return {"error": "Lazy delegation rejected — task must have real content"}

        result = await self.call_tool("web_fetch", {"url": ""}) if task_type == "fetch" \
               else {"status": "processed", "query": query, "type": task_type}

        if parent_id in self._scratchpad:
            self._scratchpad[parent_id].append(f"[{subtask.get('id')}] done: {query[:80]}")

        return result

    def write_scratchpad(self, task_id: str, note: str):
        """Any agent can write to the shared scratchpad for this coordination task."""
        self._scratchpad.setdefault(task_id, []).append(note)

    def read_scratchpad(self, task_id: str) -> list[str]:
        return self._scratchpad.get(task_id, [])
