import httpx
import pytest
import respx

from tools.repo_tool import RepoTool


@pytest.mark.asyncio
async def test_calls_return_error_without_modal_repo_url(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MODAL_REPO_URL", "")
    result = await RepoTool().read_file("github", "octocat/hello", "README.md")
    assert result == {"error": "MODAL_REPO_URL not set", "ok": False}


@pytest.mark.asyncio
async def test_clone_or_pull_posts_expected_body_and_auth(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MODAL_REPO_URL", "https://modal.example/repo")
    monkeypatch.setattr(settings, "MODAL_REPO_SECRET", "s3cr3t")

    captured = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = httpx.Request("POST", request.url).content
        import json
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "action": "cloned", "repo": "octocat/hello"})

    with respx.mock:
        respx.post("https://modal.example/repo").mock(side_effect=handler)
        result = await RepoTool().clone_or_pull("github", "octocat/hello", ref="main", token="ghp_x")

    assert result == {"ok": True, "action": "cloned", "repo": "octocat/hello"}
    assert captured["headers"]["authorization"] == "Bearer s3cr3t"
    assert captured["json"] == {
        "action": "clone_or_pull", "provider": "github", "repo": "octocat/hello",
        "ref": "main", "token": "ghp_x",
    }


@pytest.mark.asyncio
async def test_read_file_and_grep_send_the_right_action(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MODAL_REPO_URL", "https://modal.example/repo")
    monkeypatch.setattr(settings, "MODAL_REPO_SECRET", "s3cr3t")

    actions = []

    def handler(request):
        import json
        actions.append(json.loads(request.content)["action"])
        return httpx.Response(200, json={"ok": True})

    with respx.mock:
        respx.post("https://modal.example/repo").mock(side_effect=handler)
        await RepoTool().read_file("github", "octocat/hello", "README.md")
        await RepoTool().grep("github", "octocat/hello", "TODO")

    assert actions == ["read_file", "grep"]
