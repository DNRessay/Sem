import json

import httpx
import pytest
from fastapi.testclient import TestClient

from cache import ddb_backend
from gateway import auth, reset_router
from gateway.passphrase import hash_passphrase
from main import app
from tools.web import url_guard
from tools.web.fetch_tool import FetchTool


class AccountStore:
    def __init__(self):
        self.accounts = {"owner": {"id": "owner", "passphrase_hash": hash_passphrase("correct horse battery"),
                                   "role": "owner", "token_version": 0}}

    async def get_account(self, account_id):
        return self.accounts.get(account_id)

    async def get_token_version(self, account_id):
        return (self.accounts.get(account_id) or {}).get("token_version", 0)

    async def set_passphrase(self, account_id, passphrase_hash):
        a = self.accounts.get(account_id)
        if not a:
            return None
        a["passphrase_hash"], a["token_version"] = passphrase_hash, a["token_version"] + 1
        return a["token_version"]

    async def upsert_account(self, account_id, passphrase_hash, role="owner"):
        self.accounts[account_id] = {"id": account_id, "passphrase_hash": passphrase_hash, "role": role, "token_version": 0}

    async def list_sessions(self, *a, **k):
        return []


@pytest.fixture
def store(monkeypatch):
    s = AccountStore()

    async def fake():
        return s

    for target in ("storage.neon_store.get_store", "gateway.router.get_store", "gateway.reset_router.get_store"):
        monkeypatch.setattr(target, fake)
    ddb_backend._l1.clear()
    auth._versions.clear()
    yield s
    ddb_backend._l1.clear()
    auth._versions.clear()


def _login(c, passphrase, ip="1.2.3.4"):
    return c.post("/auth/login", json={"passphrase": passphrase}, headers={"x-forwarded-for": ip})


def test_login_locks_after_repeated_wrong_passphrases(store):
    c = TestClient(app)
    for _ in range(5):
        assert _login(c, "guess").status_code == 401
    assert _login(c, "correct horse battery").status_code == 429  # locked even with the right one
    assert _login(c, "correct horse battery", ip="5.6.7.8").status_code == 200  # other callers unaffected


def test_old_tokens_stop_working_once_the_version_moves(store):
    c = TestClient(app)
    token = _login(c, "correct horse battery").json()["token"]
    assert c.get("/sessions", headers={"Authorization": f"Bearer {token}"}).status_code != 401
    store.accounts["owner"]["token_version"] = 1
    auth._versions.clear()
    r = c.get("/sessions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "passphrase was changed" in r.json()["detail"]


def test_bypass_header_needs_the_exact_secret(monkeypatch):
    from gateway.router import _get_trust

    class Req:
        def __init__(self, key):
            self.headers = {"x-api-key": key}

    monkeypatch.setattr("config.settings.SECRET_KEY", "s" * 32)
    monkeypatch.setattr("config.settings.TRUST_MODE", "AUTO")
    assert _get_trust(Req("s" * 32)) == "BYPASS"
    assert _get_trust(Req("s" * 31)) == "AUTO"
    monkeypatch.setattr("config.settings.SECRET_KEY", "")
    assert _get_trust(Req("")) == "AUTO"


@pytest.fixture
def mail(monkeypatch):
    sent = []

    async def fake_send(to, subject, text):
        sent.append((to, subject, text))
        return True

    monkeypatch.setattr(reset_router, "send_mail", fake_send)
    monkeypatch.setattr("config.settings.RESET_EMAILS", "Owner@Example.com; other@example.com")
    monkeypatch.setattr("config.settings.FRONTEND_URL", "https://sem.example")
    return sent


def test_reset_only_mails_allowed_addresses_and_answers_the_same(store, mail):
    c = TestClient(app)
    stranger = c.post("/auth/reset/request", json={"email": "attacker@evil.test"})
    owner = c.post("/auth/reset/request", json={"email": " owner@example.com "})
    assert stranger.status_code == owner.status_code == 200 and stranger.json() == owner.json()
    assert [m[0] for m in mail] == ["owner@example.com"]
    assert "https://sem.example/#reset=" in mail[0][2]


def test_reset_link_sets_a_new_passphrase_once_and_signs_everyone_out(store, mail):
    c = TestClient(app)
    old = _login(c, "correct horse battery").json()["token"]
    c.post("/auth/reset/request", json={"email": "owner@example.com"})
    token = mail[0][2].split("#reset=")[1].split()[0]

    assert c.post("/auth/reset/confirm", json={"token": token, "passphrase": "short"}).status_code == 400
    r = c.post("/auth/reset/confirm", json={"token": token, "passphrase": "a much longer passphrase"})
    assert r.status_code == 200, r.text
    new = r.json()["token"]
    assert "was changed" in mail[-1][1]

    assert c.post("/auth/reset/confirm", json={"token": token, "passphrase": "another long passphrase"}).status_code == 400
    assert c.get("/sessions", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert c.get("/sessions", headers={"Authorization": f"Bearer {new}"}).status_code != 401
    assert _login(c, "a much longer passphrase", ip="9.9.9.9").status_code == 200
    assert _login(c, "correct horse battery", ip="9.9.9.8").status_code == 401


def test_reset_requests_are_rate_limited(store, mail):
    c = TestClient(app)
    codes = [c.post("/auth/reset/request", json={"email": "owner@example.com"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes and len(mail) == 3


def test_forged_reset_tokens_are_refused(store, mail):
    r = TestClient(app).post("/auth/reset/confirm", json={"token": "x" * 43, "passphrase": "a much longer passphrase"})
    assert r.status_code == 400 and "invalid or has expired" in r.json()["detail"]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:9001/2018-06-01/runtime/invocation/next", "http://localhost/", "http://169.254.169.254/latest/",
    "http://10.0.0.5/", "http://[::1]/", "file:///etc/passwd", "ftp://example.com/x", "http://0.0.0.0/",
])
async def test_private_and_odd_urls_are_never_fetched(url):
    with pytest.raises(url_guard.BlockedURL):
        await url_guard.check_url(url)
    assert "Not fetched" in (await FetchTool().fetch(url))["error"]


async def test_redirects_into_the_private_network_are_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/admin"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(url_guard.BlockedURL):
            await url_guard.safe_get(client, "http://93.184.216.34/")


def test_openclaw_needs_its_secret_and_keeps_its_own_sessions(monkeypatch):
    seen = []

    class FakeBootstrap:
        def __init__(self, **k):
            pass

        async def run(self, message, session_id, history):
            seen.append(session_id)
            yield "ok"

    async def fake_inject(*a):
        return ""

    async def fake_send(*a):
        return None

    monkeypatch.setattr("gateway.webhooks.Bootstrap", FakeBootstrap)
    monkeypatch.setattr("gateway.webhooks._tau.observe_and_inject", fake_inject)
    monkeypatch.setattr("gateway.webhooks._bridge.send_message", fake_send)
    monkeypatch.setattr("config.settings.OPENCLAW_URL", "https://claw.example")
    monkeypatch.setattr("config.settings.OPENCLAW_WEBHOOK_SECRET", "")
    c = TestClient(app)
    body = json.dumps({"channel": "telegram", "message": "hi", "session_id": "default"})
    assert c.post("/webhook/openclaw", content=body).status_code == 503
    monkeypatch.setattr("config.settings.OPENCLAW_WEBHOOK_SECRET", "claw-secret")
    assert c.post("/webhook/openclaw", content=body).status_code == 401
    assert c.post("/webhook/openclaw", content=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/webhook/openclaw", content=body, headers={"Authorization": "Bearer claw-secret"}).status_code == 200
    assert seen == ["openclaw:default"]
