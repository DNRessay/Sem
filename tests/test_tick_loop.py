import tick_handler


def test_the_tick_reuses_one_event_loop_across_warm_invocations(monkeypatch):
    loops = []

    async def run():
        import asyncio
        loops.append(asyncio.get_running_loop())
        return {"ok": True}

    monkeypatch.setattr(tick_handler, "_run", run)
    assert tick_handler.handler({}, None) == {"ok": True}
    assert tick_handler.handler({}, None) == {"ok": True}
    assert loops[0] is loops[1] and not loops[0].is_closed()
