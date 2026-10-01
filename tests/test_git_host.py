import base64
import json

import pytest
import respx
from httpx import Response

from tools.git_host import GitHost, GitHostError

GH = "https://api.github.com/repos/me/app"
GL = "https://gitlab.com/api/v4/projects/me%2Fapp"


@pytest.mark.asyncio
async def test_github_merge_and_status():
    host = GitHost("github", "me/app", "t")
    with respx.mock:
        respx.get(f"{GH}/pulls/3").mock(return_value=Response(200, json={
            "title": "x", "state": "open", "merged": False, "mergeable": True, "mergeable_state": "clean",
            "html_url": "u", "head": {"sha": "abc"}}))
        respx.get(f"{GH}/commits/abc/check-runs").mock(return_value=Response(200, json={"check_runs": [
            {"name": "test", "status": "completed", "conclusion": "success"}]}))
        merge = respx.put(f"{GH}/pulls/3/merge").mock(return_value=Response(200, json={"merged": True, "sha": "def"}))
        status = await host.pr_status(3)
        result = await host.merge_pr(3, "squash")
    assert status["mergeable"] and status["checks"][0]["conclusion"] == "success"
    assert result["ok"] and json.loads(merge.calls[0].request.content) == {"merge_method": "squash"}


@pytest.mark.asyncio
async def test_gitlab_merge_request_merge():
    host = GitHost("gitlab", "me/app", "t")
    with respx.mock:
        route = respx.put(f"{GL}/merge_requests/1/merge").mock(return_value=Response(200, json={"state": "merged", "web_url": "w"}))
        result = await host.merge_pr(1)
    assert result["ok"] and json.loads(route.calls[0].request.content) == {"squash": False}


@pytest.mark.asyncio
async def test_github_secret_is_sealed_with_the_repo_key():
    from nacl import encoding, public
    private = public.PrivateKey.generate()
    pub_b64 = private.public_key.encode(encoding.Base64Encoder()).decode()
    host = GitHost("github", "me/app", "t")
    with respx.mock:
        respx.get(f"{GH}/actions/secrets/public-key").mock(return_value=Response(200, json={"key": pub_b64, "key_id": "k1"}))
        put = respx.put(f"{GH}/actions/secrets/API_KEY").mock(return_value=Response(201))
        await host.set_secret("API_KEY", "s3cret-value")
    sent = json.loads(put.calls[0].request.content)
    assert sent["key_id"] == "k1"
    assert public.SealedBox(private).decrypt(base64.b64decode(sent["encrypted_value"])) == b"s3cret-value"


@pytest.mark.asyncio
async def test_gitlab_secret_creates_when_missing_and_masks():
    host = GitHost("gitlab", "me/app", "t")
    with respx.mock:
        respx.put(f"{GL}/variables/API_KEY").mock(return_value=Response(404, json={"message": "404 Variable Not Found"}))
        post = respx.post(f"{GL}/variables").mock(return_value=Response(201, json={}))
        result = await host.set_secret("API_KEY", "longvalue123")
    assert result["ok"] and json.loads(post.calls[0].request.content) == {"key": "API_KEY", "value": "longvalue123", "masked": True}


@pytest.mark.asyncio
async def test_errors_are_readable():
    host = GitHost("github", "me/app", "t")
    with respx.mock:
        respx.get(f"{GH}/pulls").mock(return_value=Response(401, json={"message": "Bad credentials"}))
        with pytest.raises(GitHostError, match="401"):
            await host.list_prs()


@pytest.mark.asyncio
async def test_code_agent_queues_risky_actions_and_hides_secret_values():
    from agents.code_agent import CodeAgent
    from tools.code_workspace import CodeWorkspace
    agent = CodeAgent(CodeWorkspace("github", "me/app"), pr_token="t")
    names = {t["function"]["name"] for t in agent.tools()}
    assert {"merge_pr", "set_secret", "ci_logs"} <= names
    result = await agent.dispatch("set_secret", {"name": "API_KEY", "value": "s3cret"})
    assert result["status"] == "waiting for the user's approval" and "s3cret" not in result["summary"]
    events = agent.extra_events("c1", "set_secret", {"name": "API_KEY", "value": "s3cret"}, result)
    assert events[0]["args"]["value"] != "s3cret" and agent.pending["c1"]["args"]["value"] == "s3cret"
    assert "merge_pr" not in {t["function"]["name"] for t in CodeAgent(CodeWorkspace("github", "me/app")).tools()}
