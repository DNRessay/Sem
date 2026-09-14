import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from config import settings
from gateway.auth import require_account
from gateway.connectors import _make_state, _verify_state
from main import app


class FakeStore:
    def __init__(self):
        self.connectors = {}  # (account_id, provider) -> dict

    async def list_connectors(self, account_id):
        return sorted(p for (a, p) in self.connectors if a == account_id)

    async def upsert_connector(self, account_id, provider, token, refresh_token=None, expires_at=None):
        self.connectors[(account_id, provider)] = {
            "token": token, "refresh_token": refresh_token, "expires_at": expires_at,
        }

    async def delete_connector(self, account_id, provider):
        self.connectors.pop((account_id, provider), None)

    async def get_connector(self, account_id, provider):
        c = self.connectors.get((account_id, provider))
        return {"provider": provider, **c} if c else None


@pytest.fixture
def client(monkeypatch):
    store = FakeStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.connectors.get_store", fake_get_store)
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}
    yield TestClient(app), store
    app.dependency_overrides.pop(require_account, None)


def test_save_and_list_connector(client):
    c, store = client
    resp = c.post("/connectors/github", json={"token": "ghp_test123"})
    assert resp.status_code == 200
    assert resp.json() == {"provider": "github", "connected": True}

    resp = c.get("/connectors")
    assert resp.json() == {"connectors": ["github"]}
    assert store.connectors[("owner", "github")]["token"] == "ghp_test123"


def test_save_connector_rejects_unknown_provider(client):
    c, _ = client
    resp = c.post("/connectors/bitbucket", json={"token": "x"})
    assert resp.status_code == 400


def test_save_connector_rejects_empty_token(client):
    c, _ = client
    resp = c.post("/connectors/github", json={"token": "  "})
    assert resp.status_code == 400


def test_delete_connector(client):
    c, store = client
    c.post("/connectors/gitlab", json={"token": "glpat_test"})
    resp = c.delete("/connectors/gitlab")
    assert resp.status_code == 200
    assert ("owner", "gitlab") not in store.connectors


def test_connectors_are_isolated_per_account(client):
    c, store = client
    c.post("/connectors/github", json={"token": "owner-token"})

    app.dependency_overrides[require_account] = lambda: {"account_id": "guest1", "role": "guest"}
    resp = c.get("/connectors")
    assert resp.json() == {"connectors": []}  # guest sees none of the owner's

    c.post("/connectors/github", json={"token": "guest-token"})
    assert store.connectors[("owner", "github")]["token"] == "owner-token"  # unchanged
    assert store.connectors[("guest1", "github")]["token"] == "guest-token"


def test_list_repos_without_configured_connector_errors(client):
    c, _ = client
    resp = c.get("/connectors/github/repos")
    assert resp.status_code == 400
    assert "no github connector" in resp.json()["detail"].lower()


def test_list_repos_returns_github_repos(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/user/repos").mock(
            return_value=Response(200, json=[
                {"full_name": "octocat/hello", "private": False, "default_branch": "main"},
                {"full_name": "octocat/secret", "private": True, "default_branch": "master"},
            ])
        )
        resp = c.get("/connectors/github/repos")
    assert resp.status_code == 200
    assert resp.json() == {
        "provider": "github",
        "repos": [
            {"full_name": "octocat/hello", "private": False, "default_branch": "main"},
            {"full_name": "octocat/secret", "private": True, "default_branch": "master"},
        ],
    }


def test_list_repos_returns_gitlab_repos(client):
    c, store = client
    store.connectors[("owner", "gitlab")] = {"token": "glpat_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://gitlab.com/api/v4/projects").mock(
            return_value=Response(200, json=[
                {"path_with_namespace": "group/project", "visibility": "private", "default_branch": "main"},
            ])
        )
        resp = c.get("/connectors/gitlab/repos")
    assert resp.status_code == 200
    assert resp.json() == {
        "provider": "gitlab",
        "repos": [{"full_name": "group/project", "private": True, "default_branch": "main"}],
    }


def test_list_branches_without_configured_connector_errors(client):
    c, _ = client
    resp = c.get("/connectors/github/branches", params={"repo": "octocat/hello"})
    assert resp.status_code == 400
    assert "no github connector" in resp.json()["detail"].lower()


def test_list_branches_requires_repo(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    resp = c.get("/connectors/github/branches", params={"repo": ""})
    assert resp.status_code == 400


def test_list_github_branches(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/repos/octocat/hello/branches").mock(
            return_value=Response(200, json=[{"name": "main"}, {"name": "dev"}])
        )
        resp = c.get("/connectors/github/branches", params={"repo": "octocat/hello"})
    assert resp.status_code == 200
    assert resp.json() == {"provider": "github", "repo": "octocat/hello", "branches": ["main", "dev"]}


def test_list_gitlab_branches(client):
    c, store = client
    store.connectors[("owner", "gitlab")] = {"token": "glpat_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://gitlab.com/api/v4/projects/group%2Fproject/repository/branches").mock(
            return_value=Response(200, json=[{"name": "main"}])
        )
        resp = c.get("/connectors/gitlab/branches", params={"repo": "group/project"})
    assert resp.status_code == 200
    assert resp.json() == {"provider": "gitlab", "repo": "group/project", "branches": ["main"]}


def test_list_tree_without_configured_connector_errors(client):
    c, _ = client
    resp = c.get("/connectors/github/tree", params={"repo": "octocat/hello"})
    assert resp.status_code == 400
    assert "no github connector" in resp.json()["detail"].lower()


def test_list_tree_requires_repo(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    resp = c.get("/connectors/github/tree", params={"repo": ""})
    assert resp.status_code == 400


def test_list_github_tree_root_sorts_dirs_before_files(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/repos/octocat/hello/contents").mock(
            return_value=Response(200, json=[
                {"name": "README.md", "path": "README.md", "type": "file"},
                {"name": "src", "path": "src", "type": "dir"},
            ])
        )
        resp = c.get("/connectors/github/tree", params={"repo": "octocat/hello"})
    assert resp.status_code == 200
    assert resp.json()["entries"] == [
        {"name": "src", "path": "src", "type": "dir"},
        {"name": "README.md", "path": "README.md", "type": "file"},
    ]


def test_list_github_tree_subpath_hits_contents_with_path(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/repos/octocat/hello/contents/src").mock(
            return_value=Response(200, json=[{"name": "main.py", "path": "src/main.py", "type": "file"}])
        )
        resp = c.get("/connectors/github/tree", params={"repo": "octocat/hello", "path": "src"})
    assert resp.status_code == 200
    assert resp.json()["entries"] == [{"name": "main.py", "path": "src/main.py", "type": "file"}]


def test_list_github_tree_rejects_a_file_path(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/repos/octocat/hello/contents/README.md").mock(
            return_value=Response(200, json={"name": "README.md", "path": "README.md", "type": "file"})
        )
        resp = c.get("/connectors/github/tree", params={"repo": "octocat/hello", "path": "README.md"})
    assert resp.status_code == 400
    assert "not a directory" in resp.json()["detail"].lower()


def test_list_gitlab_tree(client):
    c, store = client
    store.connectors[("owner", "gitlab")] = {"token": "glpat_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://gitlab.com/api/v4/projects/group%2Fproject/repository/tree").mock(
            return_value=Response(200, json=[
                {"name": "main.py", "path": "src/main.py", "type": "blob"},
                {"name": "utils", "path": "src/utils", "type": "tree"},
            ])
        )
        resp = c.get("/connectors/gitlab/tree", params={"repo": "group/project", "path": "src"})
    assert resp.status_code == 200
    assert resp.json()["entries"] == [
        {"name": "utils", "path": "src/utils", "type": "dir"},
        {"name": "main.py", "path": "src/main.py", "type": "file"},
    ]


def test_fetch_without_configured_connector_errors(client):
    c, _ = client
    resp = c.post("/connectors/github/fetch", json={"repo": "octocat/hello", "path": "README.md"})
    assert resp.status_code == 400
    assert "no github connector" in resp.json()["detail"].lower()


def test_fetch_requires_repo_and_path(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    resp = c.post("/connectors/github/fetch", json={"repo": "", "path": ""})
    assert resp.status_code == 400


def test_fetch_repo_without_configured_connector_errors(client):
    c, _ = client
    resp = c.post("/connectors/github/fetch-repo", json={"repo": "octocat/hello"})
    assert resp.status_code == 400
    assert "no github connector" in resp.json()["detail"].lower()


def test_fetch_repo_requires_repo(client):
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    resp = c.post("/connectors/github/fetch-repo", json={"repo": ""})
    assert resp.status_code == 400


def test_fetch_github_repo_bundles_tree_and_file_contents(client):
    import base64 as b64mod

    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/repos/octocat/hello/git/trees/main").mock(
            return_value=Response(200, json={
                "tree": [
                    {"path": "README.md", "type": "blob", "sha": "sha1"},
                    {"path": "src/main.py", "type": "blob", "sha": "sha2"},
                    {"path": "src", "type": "tree", "sha": "sha3"},
                    {"path": "logo.png", "type": "blob", "sha": "sha4"},
                    {"path": "node_modules/pkg/index.js", "type": "blob", "sha": "sha5"},
                ],
                "truncated": False,
            })
        )
        respx.get("https://api.github.com/repos/octocat/hello/git/blobs/sha1").mock(
            return_value=Response(200, json={"content": b64mod.b64encode(b"# Hello").decode(), "encoding": "base64"})
        )
        respx.get("https://api.github.com/repos/octocat/hello/git/blobs/sha2").mock(
            return_value=Response(200, json={"content": b64mod.b64encode(b"print('hi')").decode(), "encoding": "base64"})
        )
        resp = c.post("/connectors/github/fetch-repo", json={"repo": "octocat/hello", "ref": "main"})
    assert resp.status_code == 200
    data = resp.json()
    tree_part, _, files_part = data["content"].partition("</repo_tree>")
    assert "logo.png" in tree_part  # listed in the tree overview
    assert "logo.png" not in files_part  # but its binary content was never fetched (extension-filtered)
    assert "node_modules" not in files_part  # build/dep dir filtered too
    assert "# Hello" in files_part
    assert "print('hi')" in files_part
    assert data["file_count"] == 2
    assert data["truncated"] is False


def test_fetch_github_repo_truncates_when_file_cap_exceeded(client, monkeypatch):
    import base64 as b64mod

    monkeypatch.setattr("gateway.connectors._MAX_REPO_FILES", 1)
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/repos/octocat/hello/git/trees/HEAD").mock(
            return_value=Response(200, json={
                "tree": [
                    {"path": "a.py", "type": "blob", "sha": "sha1"},
                    {"path": "b.py", "type": "blob", "sha": "sha2"},
                ],
                "truncated": False,
            })
        )
        respx.get("https://api.github.com/repos/octocat/hello/git/blobs/sha1").mock(
            return_value=Response(200, json={"content": b64mod.b64encode(b"one").decode(), "encoding": "base64"})
        )
        resp = c.post("/connectors/github/fetch-repo", json={"repo": "octocat/hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_count"] == 1
    assert data["truncated"] is True


def test_fetch_github_repo_prioritizes_readme_and_entry_points(client, monkeypatch):
    """With the attach budget only fitting a handful of files, raw tree
    order (effectively alphabetical) would grab whatever sorts first rather
    than what's actually useful — README.md and main.py (an entry point)
    must be fetched over a deeply nested file and an unremarkable root file,
    even though the tree lists them in the opposite order."""
    import base64 as b64mod

    monkeypatch.setattr("gateway.connectors._MAX_REPO_FILES", 2)
    c, store = client
    store.connectors[("owner", "github")] = {"token": "ghp_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://api.github.com/repos/octocat/hello/git/trees/HEAD").mock(
            return_value=Response(200, json={
                "tree": [
                    {"path": "src/deep/nested/module.py", "type": "blob", "sha": "sha_deep"},
                    {"path": "zzz_random.py", "type": "blob", "sha": "sha_zzz"},
                    {"path": "README.md", "type": "blob", "sha": "sha_readme"},
                    {"path": "main.py", "type": "blob", "sha": "sha_main"},
                ],
                "truncated": False,
            })
        )
        respx.get("https://api.github.com/repos/octocat/hello/git/blobs/sha_readme").mock(
            return_value=Response(200, json={"content": b64mod.b64encode(b"# Hello project").decode(), "encoding": "base64"})
        )
        respx.get("https://api.github.com/repos/octocat/hello/git/blobs/sha_main").mock(
            return_value=Response(200, json={"content": b64mod.b64encode(b"print('entry')").decode(), "encoding": "base64"})
        )
        resp = c.post("/connectors/github/fetch-repo", json={"repo": "octocat/hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert "# Hello project" in data["content"]
    assert "print('entry')" in data["content"]
    assert data["file_count"] == 2  # zzz_random.py and the deeply nested file lost out on budget


def test_fetch_gitlab_repo_bundles_tree_and_file_contents(client):
    c, store = client
    store.connectors[("owner", "gitlab")] = {"token": "glpat_test", "refresh_token": None, "expires_at": None}
    with respx.mock:
        respx.get("https://gitlab.com/api/v4/projects/group%2Fproject/repository/tree").mock(
            return_value=Response(200, json=[
                {"path": "README.md", "type": "blob", "id": "blob1"},
                {"path": "src/main.py", "type": "blob", "id": "blob2"},
                {"path": "src", "type": "tree", "id": "tree1"},
            ])
        )
        respx.get("https://gitlab.com/api/v4/projects/group%2Fproject/repository/blobs/blob1/raw").mock(
            return_value=Response(200, content=b"# Hello")
        )
        respx.get("https://gitlab.com/api/v4/projects/group%2Fproject/repository/blobs/blob2/raw").mock(
            return_value=Response(200, content=b"print('hi')")
        )
        resp = c.post("/connectors/gitlab/fetch-repo", json={"repo": "group/project"})
    assert resp.status_code == 200
    data = resp.json()
    assert "# Hello" in data["content"]
    assert "print('hi')" in data["content"]
    assert data["file_count"] == 2
    assert data["truncated"] is False


def test_authorize_errors_when_oauth_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "")
    c, _ = client
    resp = c.get("/connectors/github/authorize")
    assert resp.status_code == 400
    assert "isn't configured" in resp.json()["detail"].lower()


def test_authorize_returns_provider_consent_url(client, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "abc123")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")
    c, _ = client
    resp = c.get("/connectors/github/authorize")
    assert resp.status_code == 200
    url = resp.json()["url"]
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=abc123" in url
    assert "redirect_uri=" in url
    assert "state=" in url


def test_state_round_trips_and_rejects_tampering():
    state = _make_state("github", "owner")
    assert _verify_state(state, "github") == "owner"
    assert _verify_state(state, "gitlab") is None  # wrong provider
    assert _verify_state(state + "x", "github") is None  # tampered


def test_state_carries_the_authorizing_account_not_just_owner():
    state = _make_state("github", "guest7")
    assert _verify_state(state, "github") == "guest7"


def test_callback_rejects_missing_or_invalid_state(client):
    c, _ = client
    resp = c.get("/connectors/github/callback", params={"code": "somecode", "state": "bogus"})
    assert resp.status_code == 200  # renders an HTML error page, not a raw error
    assert "failed" in resp.text.lower()


def test_callback_exchanges_code_and_stores_token_for_the_authorizing_account(client, monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_CLIENT_ID", "abc123")
    monkeypatch.setattr(settings, "GITHUB_CLIENT_SECRET", "shh")
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")
    c, store = client

    # A guest's own /authorize call would mint a state carrying their id —
    # the callback (no auth header available) must honor that, not silently
    # attribute the connection to whichever account is "current" server-side.
    state = _make_state("github", "guest3")
    with respx.mock:
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=Response(200, json={"access_token": "gho_realtoken", "token_type": "bearer"})
        )
        resp = c.get("/connectors/github/callback", params={"code": "realcode", "state": state})

    assert resp.status_code == 200
    assert "connected" in resp.text.lower()
    assert store.connectors[("guest3", "github")]["token"] == "gho_realtoken"
    assert ("owner", "github") not in store.connectors
