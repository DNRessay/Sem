import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def calls(monkeypatch):
    seen = {"log": [], "deliver": []}

    async def fake_log(session, agent, action):
        seen["log"].append((session, action))

    async def fake_deliver(account_id, title, text):
        seen["deliver"].append((title, text))
        return ["app"]

    monkeypatch.setattr("gateway.webhooks.activity.log", fake_log)
    monkeypatch.setattr("agents.kairos.deliver", fake_deliver)
    monkeypatch.setattr("config.settings.GITHUB_WEBHOOK_SECRET", "s3")
    return seen


def _post(event, payload, headers=None):
    body = json.dumps(payload)
    sig = "sha256=" + hmac.new(b"s3", body.encode(), hashlib.sha256).hexdigest()
    return TestClient(app).post("/webhook/github", content=body,
                                headers={"x-github-event": event, "x-hub-signature-256": sig, **(headers or {})})


def test_failed_ci_run_is_delivered_and_logged(calls):
    resp = _post("workflow_run", {"action": "completed", "repository": {"full_name": "me/app"},
                                  "workflow_run": {"name": "CI", "conclusion": "failure", "head_branch": "main",
                                                   "head_commit": {"message": "fix x\n\nbody"}, "html_url": "u"}})
    assert resp.json()["delivered"] == ["app"]
    title, text = calls["deliver"][0]
    assert title == "CI failed: me/app" and "CI failed on main (fix x)" in text
    assert calls["log"][0][0] == "github"


def test_new_issue_is_delivered(calls):
    _post("issues", {"action": "opened", "repository": {"full_name": "me/app"},
                     "issue": {"number": 7, "title": "Broken", "user": {"login": "sam"}, "html_url": "u"}})
    assert calls["deliver"][0][0] == "New issue: me/app" and "#7 Broken by sam" in calls["deliver"][0][1]


def test_pull_request_is_only_logged(calls):
    resp = _post("pull_request", {"action": "closed", "repository": {"full_name": "me/app"},
                                  "pull_request": {"number": 3, "title": "Feat", "merged": True}})
    assert resp.json()["delivered"] == [] and not calls["deliver"]
    assert calls["log"] == [("github", "me/app PR #3 closed (merged): Feat")]


def test_passing_ci_is_not_delivered(calls):
    _post("workflow_run", {"action": "completed", "workflow_run": {"conclusion": "success"}})
    assert not calls["deliver"]


def test_signature_is_required(calls, monkeypatch):
    assert _post("ping", {"zen": "hi"}, {"x-hub-signature-256": "sha256=bad"}).status_code == 401
    assert _post("ping", {"zen": "hi"}).json()["status"] == "ok"
    monkeypatch.setattr("config.settings.GITHUB_WEBHOOK_SECRET", "")
    assert _post("ping", {"zen": "hi"}).status_code == 401  # no secret set: nothing gets in
