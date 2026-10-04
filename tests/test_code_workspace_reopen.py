from tools import code_workspace


async def test_a_missing_clone_is_made_again_once_and_the_call_retried(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((json["action"], json.get("token")))
            if json["action"] == "clone_or_pull":
                return FakeResponse({"ok": True, "action": "cloned"})
            if len([c for c in calls if c[0] == "list_dir"]) == 1:
                return FakeResponse({"ok": False, "error": "repo not cloned yet — call clone_or_pull first"})
            return FakeResponse({"ok": True, "entries": ["README.md"]})

    monkeypatch.setattr(code_workspace.settings, "MODAL_REPO_URL", "https://repo.example")
    monkeypatch.setattr(code_workspace.httpx, "AsyncClient", FakeClient)
    ws = code_workspace.CodeWorkspace("github", "me/site", token="tok")
    assert (await ws.list_dir())["entries"] == ["README.md"]
    assert calls == [("list_dir", None), ("clone_or_pull", "tok"), ("list_dir", None)]
