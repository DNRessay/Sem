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

    monkeypatch.setattr("tick_handler.KairosDaemon", FakeKairos)
    monkeypatch.setattr("tick_handler.DreamAgent", FakeDream)

    result = tick_handler.handler({}, None)

    assert calls == ["kairos", "dream"]
    assert result["status"] == "ok"
    assert result["kairos_audit"] == [{"action": "kairos:tick"}]
    assert result["dream"] == {"status": "gates_not_met", "ready": False}
