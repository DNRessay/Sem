import asyncio


class SubAgentDelegation:
    """Runs one task through several agents in parallel via CABLES MAN.
    (The old file-mailbox "teammate" and git "worktree" modes are gone: no
    process ever answered the mailbox, and Lambda has no writable git
    checkout — the Code tab's Modal workspace covers that use instead.)"""

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
