"""
Medium-tier entrypoint. EventBridge invokes this on a schedule (see template.yaml)
as a stand-in for KAIROS's always-on daemon loop, which can't run inside Lambda's
freeze/thaw execution model. Same decision logic, same 15s tick budget — it just
runs once per invocation instead of once per 60s inside an infinite loop.

Also checks DREAM's real (Neon-backed) consolidation gate on the same
schedule — see agents/dream_agent.py's docstring for why that gate had to
move out of in-memory instance state. Most ticks are a fast no-op here:
DreamAgent.run() itself checks the gate first and returns immediately
when it isn't met, same as KairosDaemon.run_once() already does for its
own decision logic.
"""
import asyncio

from agents.dream_agent import DreamAgent
from agents.kairos import KairosDaemon


def handler(event, context):
    return asyncio.run(_run())


async def _run():
    kairos = KairosDaemon()
    await kairos.run_once()

    dream = DreamAgent()
    dream_result = await dream.run({})

    return {"status": "ok", "kairos_audit": kairos.get_audit(), "dream": dream_result}
