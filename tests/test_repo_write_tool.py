import pytest
import respx
from httpx import Response

from tools.repo_write_tool import RepoWriteTool, branch_name, bump_version, slugify


def test_bump_version_patch():
    assert bump_version("1.2.3", "patch") == "1.2.4"


def test_bump_version_minor_resets_patch():
    assert bump_version("1.2.3", "minor") == "1.3.0"


def test_bump_version_handles_missing_or_invalid_version():
    assert bump_version("", "patch") == "0.0.1"
    assert bump_version("not-a-version", "minor") == "0.1.0"


def test_bump_version_rejects_major():
    with pytest.raises(ValueError):
        bump_version("1.2.3", "major")


def test_bump_version_rejects_unknown_level():
    with pytest.raises(ValueError):
        bump_version("1.2.3", "epic")


def test_slugify_lowercases_and_strips_punctuation():
    assert slugify("Fix Null Pointer in BuddyAgent!!") == "fix-null-pointer-in-buddyagent"


def test_slugify_truncates_long_text():
    assert len(slugify("x" * 200)) == 50


def test_slugify_empty_text_falls_back():
    assert slugify("...") == "change"


def test_branch_name_patch_uses_fix_prefix():
    assert branch_name("patch", "1.2.4", "null pointer") == "fix/v1.2.4-null-pointer"


def test_branch_name_minor_uses_feat_prefix():
    assert branch_name("minor", "1.3.0", "add search") == "feat/v1.3.0-add-search"


GITHUB_API = "https://api.github.com"


@pytest.mark.asyncio
async def test_propose_fix_full_flow_on_github():
    tool = RepoWriteTool()

    with respx.mock:
        respx.get(f"{GITHUB_API}/repos/me/repo").mock(
            return_value=Response(200, json={"default_branch": "main"}),
        )
        respx.get(f"{GITHUB_API}/repos/me/repo/git/ref/heads/main").mock(
            return_value=Response(200, json={"object": {"sha": "basesha123"}}),
        )
        # No existing VERSION file — 404
        respx.get(f"{GITHUB_API}/repos/me/repo/contents/VERSION").mock(
            return_value=Response(404),
        )
        respx.post(f"{GITHUB_API}/repos/me/repo/git/refs").mock(
            return_value=Response(201, json={}),
        )
        # No existing content of the changed file either — 404
        respx.get(f"{GITHUB_API}/repos/me/repo/contents/agents/buddy.py").mock(
            return_value=Response(404),
        )
        respx.put(f"{GITHUB_API}/repos/me/repo/contents/agents/buddy.py").mock(
            return_value=Response(201, json={}),
        )
        respx.put(f"{GITHUB_API}/repos/me/repo/contents/VERSION").mock(
            return_value=Response(201, json={}),
        )
        respx.post(f"{GITHUB_API}/repos/me/repo/pulls").mock(
            return_value=Response(201, json={"html_url": "https://github.com/me/repo/pull/1", "number": 1}),
        )

        result = await tool.propose_fix(
            provider="github",
            repo="me/repo",
            token="tok",
            level="patch",
            slug="null pointer in buddy agent",
            files={"agents/buddy.py": "fixed content"},
            commit_message="Fix null pointer in BuddyAgent",
        )

    assert result["ok"] is True
    assert result["version"] == "0.0.1"
    assert result["branch"] == "fix/v0.0.1-null-pointer-in-buddy-agent"
    assert result["url"] == "https://github.com/me/repo/pull/1"


@pytest.mark.asyncio
async def test_propose_fix_never_touches_the_default_branch():
    """The PR's head is always the new branch, never main — this is the
    whole safety property the design relies on."""
    tool = RepoWriteTool()

    with respx.mock:
        respx.get(f"{GITHUB_API}/repos/me/repo").mock(return_value=Response(200, json={"default_branch": "main"}))
        respx.get(f"{GITHUB_API}/repos/me/repo/git/ref/heads/main").mock(
            return_value=Response(200, json={"object": {"sha": "basesha"}}),
        )
        respx.get(f"{GITHUB_API}/repos/me/repo/contents/VERSION").mock(return_value=Response(404))
        respx.post(f"{GITHUB_API}/repos/me/repo/git/refs").mock(return_value=Response(201, json={}))
        respx.get(f"{GITHUB_API}/repos/me/repo/contents/x.py").mock(return_value=Response(404))
        respx.put(f"{GITHUB_API}/repos/me/repo/contents/x.py").mock(return_value=Response(201, json={}))
        respx.put(f"{GITHUB_API}/repos/me/repo/contents/VERSION").mock(return_value=Response(201, json={}))
        pr_route = respx.post(f"{GITHUB_API}/repos/me/repo/pulls").mock(
            return_value=Response(201, json={"html_url": "https://github.com/me/repo/pull/2", "number": 2}),
        )

        await tool.propose_fix(
            provider="github", repo="me/repo", token="tok", level="patch",
            slug="x", files={"x.py": "y"}, commit_message="fix",
        )

    import json
    pr_body = json.loads(pr_route.calls[0].request.content)
    assert pr_body["base"] == "main"
    assert pr_body["head"] != "main"
    assert pr_body["head"].startswith("fix/")


@pytest.mark.asyncio
async def test_propose_fix_rejects_major():
    tool = RepoWriteTool()
    result = await tool.propose_fix(
        provider="github", repo="me/repo", token="tok", level="major",
        slug="x", files={"x.py": "y"}, commit_message="fix",
    )
    assert result["ok"] is False
    assert "major" in result["error"].lower()


@pytest.mark.asyncio
async def test_propose_fix_rejects_no_files():
    tool = RepoWriteTool()
    result = await tool.propose_fix(
        provider="github", repo="me/repo", token="tok", level="patch",
        slug="x", files={}, commit_message="fix",
    )
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_propose_fix_stops_if_branch_creation_fails():
    tool = RepoWriteTool()
    with respx.mock:
        respx.get(f"{GITHUB_API}/repos/me/repo").mock(return_value=Response(200, json={"default_branch": "main"}))
        respx.get(f"{GITHUB_API}/repos/me/repo/git/ref/heads/main").mock(
            return_value=Response(200, json={"object": {"sha": "basesha"}}),
        )
        respx.get(f"{GITHUB_API}/repos/me/repo/contents/VERSION").mock(return_value=Response(404))
        respx.post(f"{GITHUB_API}/repos/me/repo/git/refs").mock(
            return_value=Response(422, text="Reference already exists"),
        )
        pr_route = respx.post(f"{GITHUB_API}/repos/me/repo/pulls").mock(return_value=Response(201, json={}))

        result = await tool.propose_fix(
            provider="github", repo="me/repo", token="tok", level="patch",
            slug="x", files={"x.py": "y"}, commit_message="fix",
        )

    assert result["ok"] is False
    assert not pr_route.calls  # never got far enough to open a PR
