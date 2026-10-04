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
from tau.pacific import refresh_profile

# One event loop for the life of the Lambda instance: asyncio.run() made a new loop per invocation and closed
# it, so on a warm instance the database pool and HTTP clients still bound to the old loop failed with
# "Event loop is closed" (the second tick within a few minutes always crashed).
_loop = asyncio.new_event_loop()


def handler(event, context):
    asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(_run())


async def _run():
    kairos = KairosDaemon()
    await kairos.run_once()

    dream = DreamAgent()
    dream_result = await dream.run({})

    # Once a day: re-read the owner's personality/style profile (tau/pacific.py).
    try:
        pacific = await refresh_profile()
    except Exception as e:
        pacific = {"error": str(e)[:300]}

    # One scheduled Code tab automation per tick at most (see pipeline/code_tasks.py).
    try:
        automation = await run_due_automation()
    except Exception as e:  # a broken automation must not take KAIROS/DREAM down with it
        automation = {"error": str(e)[:300]}

    # Videos: finish any whose Modal "done" callback was missed (gateway/design_router.advance_all).
    try:
        from gateway.design_router import advance_all
        videos = await advance_all()
    except Exception as e:
        videos = {"error": str(e)[:300]}

    return {"status": "ok", "kairos_audit": kairos.get_audit(), "dream": dream_result, "pacific": pacific,
            "automation": automation, "videos": videos}
