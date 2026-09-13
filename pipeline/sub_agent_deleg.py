import asyncio
import json
import os
from pathlib import Path


class SubAgentDelegation:
    MAILBOX_DIR = "./data/mailbox"

    async def fork(self, task: dict, agent_types: list[str]) -> list[dict]:
        from core.cables_man import CablesMan
        cables = CablesMan()
        results = await asyncio.gather(*[
            cables.route({**task, "agent": a}) for a in agent_types
        ], return_exceptions=True)
        return [
            r if not isinstance(r, Exception) else {"error": str(r)}
            for r in results
        ]

    async def teammate(self, task: dict, agent_id: str) -> dict:
        os.makedirs(self.MAILBOX_DIR, exist_ok=True)
        mailbox = Path(f"{self.MAILBOX_DIR}/{agent_id}.json")
        mailbox.write_text(json.dumps(task))

        for _ in range(60):
            await asyncio.sleep(2)
            result_path = Path(f"{self.MAILBOX_DIR}/{agent_id}_result.json")
            if result_path.exists():
                result = json.loads(result_path.read_text())
                result_path.unlink()
                mailbox.unlink(missing_ok=True)
                return result

        return {"status": "timeout", "agent": agent_id}

    async def worktree(self, task: dict, branch: str = None) -> dict:
        import time
        branch = branch or f"agent-{int(time.time())}"
        try:
            proc = await asyncio.create_subprocess_shell(
                f"git worktree add ./data/worktrees/{branch} -b {branch}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            return {"status": "worktree_created", "branch": branch, "task": task}
        except Exception as e:
            return {"error": str(e)}