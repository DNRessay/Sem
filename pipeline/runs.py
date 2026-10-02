"""Agent runs that outlive the browser connection.

A phone that locks or switches apps drops the SSE connection. Without this, Starlette
cancels the stream and the agent dies mid-task. durable() runs the stream in its own
task, saves every event (batched) to Postgres, and when the client goes away keeps the
request — and so the Lambda invocation — alive until the run ends. The page fetches
what it missed from GET /runs/{run_id} (gateway/runs_router.py) when it comes back.

Each saved event is one `data:` line; its seq is its 1-based position in the stream
(not counting [DONE]), so the browser can count lines and ask for the rest."""
import asyncio
import json
import re
import time
import uuid

import anyio
from fastapi.responses import StreamingResponse

from storage.neon_store import get_store

_RUN_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
FLUSH_SECONDS = 0.4
CANCEL_POLL_SECONDS = 2.0
_live: set[asyncio.Task] = set()


def run_id_for(body: dict) -> str:
    rid = str(body.get("run_id") or "")
    return rid if _RUN_ID.fullmatch(rid) else uuid.uuid4().hex


def _data(line: str) -> list[str]:
    return [ln[6:] for ln in line.splitlines() if ln.startswith("data: ") and ln[6:] != "[DONE]"]


class _Recorder:
    """Batches events to the store; a store outage only costs the resume ability, never the live run."""

    def __init__(self, run_id: str):
        self.run_id, self.seq, self.pending, self.last = run_id, 0, [], time.monotonic()
        self.status, self.ok = "running", True

    async def _store(self):
        return await get_store() if self.ok else None

    async def start(self, account_id: str, tab: str):
        try:
            await (await self._store()).start_run(self.run_id, account_id, tab)
        except Exception:
            self.ok = False

    def add(self, line: str):
        for data in _data(line):
            self.seq += 1
            self.pending.append((self.seq, data))

    async def flush(self, force: bool = False):
        if not self.ok or (not force and time.monotonic() - self.last < FLUSH_SECONDS):
            return
        batch, self.pending, self.last = self.pending, [], time.monotonic()
        try:
            self.status = await (await self._store()).add_run_events(self.run_id, batch) or self.status
        except Exception:
            self.ok = False

    async def finish(self, status: str):
        await self.flush(force=True)
        try:
            if self.ok:
                await (await self._store()).set_run_status(self.run_id, status)
        except Exception:
            pass


async def _drive(gen, rec: _Recorder, account_id: str, tab: str, queue: asyncio.Queue):
    await rec.start(account_id, tab)

    def emit(line: str):
        queue.put_nowait(line)
        rec.add(line)

    async def consume():
        try:
            async for line in gen:
                emit(line)
                await rec.flush()
        finally:
            await gen.aclose()

    async def watch_cancel():
        while rec.ok and rec.status != "cancelled":
            await asyncio.sleep(CANCEL_POLL_SECONDS)
            await rec.flush(force=True)

    status = "done"
    consumer, watcher = asyncio.create_task(consume()), asyncio.create_task(watch_cancel())
    try:
        await asyncio.wait({consumer, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if consumer.done():
            consumer.result()
        elif rec.status == "cancelled":
            consumer.cancel()
            status = "cancelled"
            emit(f"data: {json.dumps({'type': 'error', 'text': 'Stopped.'})}\n\n")
        else:
            await consumer  # the store is unreachable; the live run carries on without it
    except Exception as e:
        status = "error"
        emit(f"data: {json.dumps({'type': 'error', 'text': f'Run failed: {str(e)[:300]}'})}\n\n")
    finally:
        watcher.cancel()
        if not consumer.done():
            consumer.cancel()
        if status != "done":
            queue.put_nowait("data: [DONE]\n\n")
        queue.put_nowait(None)
        await rec.finish(status)


def durable(gen, account_id: str, body: dict, tab: str) -> StreamingResponse:
    """Wraps an SSE generator (yielding "data: ...\\n\\n" strings) so the run survives a disconnect."""
    rec = _Recorder(run_id_for(body))
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_drive(gen, rec, account_id, tab, queue))
    _live.add(task)
    task.add_done_callback(_live.discard)

    async def stream():
        try:
            while (line := await queue.get()) is not None:
                yield line
        finally:
            if not task.done():
                # The client left (phone locked, app switched). Finish the run anyway; the page
                # picks up the rest from /runs/{run_id}. Shielded: Starlette cancels this generator.
                with anyio.CancelScope(shield=True):
                    await asyncio.wait({task})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"X-Run-Id": rec.run_id, "Access-Control-Expose-Headers": "X-Run-Id"})
