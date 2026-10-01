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
from pipeline.code_tasks import run_due_automation


def handler(event, context):
    return asyncio.run(_run())


async def _run():
    kairos = KairosDaemon()
    await kairos.run_once()

    dream = DreamAgent()
    dream_result = await dream.run({})

    # One scheduled Code tab automation per tick at most (see pipeline/code_tasks.py).
    try:
        automation = await run_due_automation()
    except Exception as e:  # a broken automation must not take KAIROS/DREAM down with it
        automation = {"error": str(e)[:300]}

    return {"status": "ok", "kairos_audit": kairos.get_audit(), "dream": dream_result, "automation": automation}
