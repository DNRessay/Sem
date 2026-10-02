import asyncio
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gateway import runs_router
from gateway.auth import require_account
from pipeline import runs


class RunStore:
    def __init__(self):
        self.runs, self.events = {}, {}

    async def start_run(self, run_id, account_id, tab):
        self.runs.setdefault(run_id, {"account": account_id, "tab": tab, "status": "running", "updated_at": 0})
        self.events.setdefault(run_id, {})

    async def add_run_events(self, run_id, events):
        self.events[run_id].update(dict(events))
        return self.runs[run_id]["status"]

    async def set_run_status(self, run_id, status, account_id=None):
        run = self.runs.get(run_id)
        if not run or (account_id and run["account"] != account_id):
            return False
        run["status"] = status
        return True

    async def get_run(self, run_id, account_id, after=0, limit=100):
        run = self.runs.get(run_id)
        if not run or run["account"] != account_id:
            return None
        import time
        evs = [{"seq": s, "data": d} for s, d in sorted(self.events[run_id].items()) if s > after][:limit]
        return {"status": run["status"], "updated_at": time.time(), "events": evs}


@pytest.fixture
def store(monkeypatch):
    s = RunStore()

    async def fake():
        return s

    monkeypatch.setattr(runs, "get_store", fake)
    monkeypatch.setattr(runs_router, "get_store", fake)
    monkeypatch.setattr(runs, "FLUSH_SECONDS", 0)
    monkeypatch.setattr(runs, "CANCEL_POLL_SECONDS", 0.02)
    return s


def make_app(steps, delay=0.0):
    app = FastAPI()
    app.include_router(runs_router.router)
    app.dependency_overrides[require_account] = lambda: {"account_id": "me"}

    @app.post("/go")
    async def go(request: Request):
        body = await request.json()

        async def stream():
            for i in range(steps):
                await asyncio.sleep(delay)
                yield f"data: {json.dumps({'type': 'text', 'text': f'step {i + 1}'})}\n\n"
            yield "data: [DONE]\n\n"

        return runs.durable(stream(), "me", body, "code")

    return app


def test_live_stream_is_unchanged_and_recorded(store):
    c = TestClient(make_app(3))
    r = c.post("/go", json={"run_id": "run-abc123"})
    assert r.headers["x-run-id"] == "run-abc123"
    lines = [ln for ln in r.text.split("\n") if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]" and len(lines) == 4
    got = c.get("/runs/run-abc123?after=1").json()
    assert got["status"] == "done"
    assert [e["seq"] for e in got["events"]] == [2, 3]
    assert got["events"][-1]["event"] == {"type": "text", "text": "step 3"}
    assert TestClient(make_app(0)).get("/runs/nope").status_code == 404


async def test_run_finishes_after_the_client_disconnects(store):
    """The phone locks after the first event: the run must still reach the end and be fetchable."""
    app = make_app(5, delay=0.02)
    sent, got_first = [], asyncio.Event()

    async def receive():
        if not sent:
            sent.append(1)
            return {"type": "http.request", "body": json.dumps({"run_id": "run-gone-away"}).encode(), "more_body": False}
        await got_first.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.body" and msg.get("body"):
            got_first.set()
            if len(sent) > 1:
                raise OSError("client went away")
            sent.append(2)

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": "/go", "raw_path": b"/go", "query_string": b"", "root_path": "",
             "headers": [(b"content-type", b"application/json")], "client": ("t", 1), "server": ("t", 80)}
    try:
        await app(scope, receive, send)
    except OSError:
        pass
    await asyncio.sleep(0.3)
    assert store.runs["run-gone-away"]["status"] == "done"
    assert len(store.events["run-gone-away"]) == 5


async def test_cancel_stops_the_run(store):
    app = make_app(200, delay=0.01)
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        task = asyncio.create_task(c.post("/go", json={"run_id": "run-to-stop"}))
        await asyncio.sleep(0.15)
        assert (await c.post("/runs/run-to-stop/cancel")).json() == {"cancelled": True}
        r = await asyncio.wait_for(task, 5)
    assert '"Stopped."' in r.text and r.text.rstrip().endswith("data: [DONE]")
    assert store.runs["run-to-stop"]["status"] == "cancelled"
    assert len(store.events["run-to-stop"]) < 100


async def test_store_outage_never_breaks_the_live_run(monkeypatch):
    async def broken():
        raise RuntimeError("neon asleep")

    monkeypatch.setattr(runs, "get_store", broken)
    r = TestClient(make_app(3)).post("/go", json={})
    assert r.text.count("data: ") == 4 and "step 3" in r.text
