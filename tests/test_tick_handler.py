import tick_handler


def test_handler_runs_kairos_and_dream_and_returns_both_results(monkeypatch):
    calls = []

    class FakeKairos:
        async def run_once(self):
            calls.append("kairos")

        def get_audit(self):
            return [{"action": "kairos:tick"}]

    class FakeDream:
        async def run(self, task):
            calls.append("dream")
            return {"status": "gates_not_met", "ready": False}

    async def fake_pacific():
        calls.append("pacific")
        return None

    async def fake_automation():
        calls.append("automation")
        return None

    monkeypatch.setattr("tick_handler.KairosDaemon", FakeKairos)
    monkeypatch.setattr("tick_handler.DreamAgent", FakeDream)
    monkeypatch.setattr("tick_handler.refresh_profile", fake_pacific)
    monkeypatch.setattr("tick_handler.run_due_automation", fake_automation)

    result = tick_handler.handler({}, None)

    assert calls == ["kairos", "dream", "pacific", "automation"]
    assert result["status"] == "ok"
    assert result["kairos_audit"] == [{"action": "kairos:tick"}]
    assert result["dream"] == {"status": "gates_not_met", "ready": False}
