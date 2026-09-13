"""
Medium-tier entrypoint. EventBridge invokes this on a schedule (see template.yaml)
as a stand-in for KAIROS's always-on daemon loop, which can't run inside Lambda's
freeze/thaw execution model. Same decision logic, same 15s tick budget — it just
runs once per invocation instead of once per 60s inside an infinite loop.
"""
import asyncio

from agents.kairos import KairosDaemon


def handler(event, context):
    kairos = KairosDaemon()
    asyncio.run(kairos.run_once())
    return {"status": "ok", "audit": kairos.get_audit()}
