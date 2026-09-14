import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cache.sys_cache import SysCache
from gateway.connectors import router as connectors_router
from gateway.router import router
from gateway.skills import router as skills_router
from gateway.webhooks import webhook_router
from storage.neon_store import get_store

sys_cache = SysCache()

# Kairos is a Heavy-tier always-on daemon (infinite loop) — it cannot run inside
# a Lambda execution environment, which freezes between invocations. In Lambda,
# the equivalent "tick" is triggered on a schedule instead — see tick_handler.py
# and the EventBridge rule in template.yaml.
_IS_LAMBDA = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_store()
    sys_cache.warm()

    kairos_task = None
    if not _IS_LAMBDA:
        import asyncio

        from agents.kairos import KairosDaemon
        kairos = KairosDaemon()
        kairos_task = asyncio.create_task(kairos.start())

    yield

    if kairos_task:
        kairos.stop()
        kairos_task.cancel()

    store = await get_store()
    await store.close()


app = FastAPI(title="SEMBLANCE", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(connectors_router)
app.include_router(skills_router)
app.include_router(webhook_router)
