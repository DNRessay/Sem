import pytest

from pipeline.repo_context import detect_repo_intent, repo_status_label, run_repo_intent


def test_detect_repo_intent_finds_readme_phrasing():
    assert detect_repo_intent("what's in the readme")[0] == "read"
    assert detect_repo_intent("what's in the readme")[1] == "README.md"
    assert detect_repo_intent("read the readme")[0] == "read"
    assert detect_repo_intent("show me the readme")[0] == "read"


def test_detect_repo_intent_finds_explicit_file_read():
    assert detect_repo_intent("read file: main.py") == ("read", "main.py")
    assert detect_repo_intent("read the file config.py") == ("read", "config.py")


def test_detect_repo_intent_finds_natural_read_phrasings():
    """These natural phrasings used to fall through to no repo intent at
    all — only the exact "read file: X" shape matched, so the model just
    answered from whatever happened to still be in short-term conversation
    context instead of actually reading the live cloned repo."""
    assert detect_repo_intent("what does index look like") == ("read", "index")
    assert detect_repo_intent("Can u tell me what the main looks like") == ("read", "main")
    assert detect_repo_intent("what's in index") == ("read", "index")
    assert detect_repo_intent("show me main.py") == ("read", "main.py")
    assert detect_repo_intent("give me a copy of the content of index") == ("read", "index")
    assert detect_repo_intent("give me a copy of config.py") == ("read", "config.py")
    assert detect_repo_intent("contents of index.html") == ("read", "index.html")


def test_detect_repo_intent_finds_grep_phrasing():
    assert detect_repo_intent("search the repo for TODO") == ("grep", "TODO")
    assert detect_repo_intent("grep the codebase for save_turn") == ("grep", "save_turn")


def test_detect_repo_intent_returns_none_for_ordinary_chat():
    assert detect_repo_intent("hey, how's it going?") is None
    assert detect_repo_intent("what's the weather like") is None


def test_detect_repo_intent_rejects_generic_pronoun_targets():
    """The broadened read-file patterns capture whatever word follows their
    trigger phrase — for a generic "what's in here" (used right after
    attaching a repo, common phrasing) that word is a pronoun, not a real
    filename, and firing a bogus repo_read with target="here" against a
    real DB/Modal call is exactly the false-positive this guards against."""
    assert detect_repo_intent("what's in here") is None
    assert detect_repo_intent("what's in this") is None
    assert detect_repo_intent("show me everything") is None


def test_status_label_differs_by_kind():
    assert repo_status_label("read", "README.md") == "Reading README.md…"
    assert repo_status_label("grep", "TODO") == 'Searching the repo for "TODO"…'


@pytest.mark.asyncio
async def test_run_repo_intent_returns_empty_with_no_active_repo(monkeypatch):
    class FakeStore:
        async def get_active_repo(self, session_id):
            return None

    async def fake_get_store():
        return FakeStore()

    monkeypatch.setattr("pipeline.repo_context.get_store", fake_get_store)
    result = await run_repo_intent("read", "README.md", "sess1")
    assert result == ""


@pytest.mark.asyncio
async def test_run_repo_intent_read_wraps_content(monkeypatch):
    class FakeStore:
        async def get_active_repo(self, session_id):
            return {"provider": "github", "repo": "octocat/hello", "ref": "main"}

    async def fake_get_store():
        return FakeStore()

    class FakeRegistry:
        async def execute(self, tool_name, args):
            assert tool_name == "repo_read"
            assert args == {"provider": "github", "repo": "octocat/hello", "path": "README.md"}
            return {"ok": True, "content": "# Hello", "path": "README.md"}

    monkeypatch.setattr("pipeline.repo_context.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.repo_context.get_registry", lambda: FakeRegistry())
    result = await run_repo_intent("read", "README.md", "sess1")
    assert '<repo_file repo="octocat/hello" path="README.md">' in result
    assert "# Hello" in result


@pytest.mark.asyncio
async def test_run_repo_intent_read_returns_empty_on_tool_failure(monkeypatch):
    class FakeStore:
        async def get_active_repo(self, session_id):
            return {"provider": "github", "repo": "octocat/hello", "ref": ""}

    async def fake_get_store():
        return FakeStore()

    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {"ok": False, "error": "file not found"}

    monkeypatch.setattr("pipeline.repo_context.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.repo_context.get_registry", lambda: FakeRegistry())
    result = await run_repo_intent("read", "missing.py", "sess1")
    assert result == ""


@pytest.mark.asyncio
async def test_run_repo_intent_grep_wraps_matches(monkeypatch):
    class FakeStore:
        async def get_active_repo(self, session_id):
            return {"provider": "github", "repo": "octocat/hello", "ref": ""}

    async def fake_get_store():
        return FakeStore()

    class FakeRegistry:
        async def execute(self, tool_name, args):
            assert tool_name == "repo_grep"
            assert args == {"provider": "github", "repo": "octocat/hello", "term": "TODO"}
            return {"ok": True, "matches": [{"path": "a.py", "line": "3", "text": "# TODO fix this"}]}

    monkeypatch.setattr("pipeline.repo_context.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.repo_context.get_registry", lambda: FakeRegistry())
    result = await run_repo_intent("grep", "TODO", "sess1")
    assert 'a.py:3: # TODO fix this' in result
    assert '<repo_grep repo="octocat/hello" term="TODO">' in result


@pytest.mark.asyncio
async def test_run_repo_intent_grep_returns_empty_with_no_matches(monkeypatch):
    class FakeStore:
        async def get_active_repo(self, session_id):
            return {"provider": "github", "repo": "octocat/hello", "ref": ""}

    async def fake_get_store():
        return FakeStore()

    class FakeRegistry:
        async def execute(self, tool_name, args):
            return {"ok": True, "matches": []}

    monkeypatch.setattr("pipeline.repo_context.get_store", fake_get_store)
    monkeypatch.setattr("pipeline.repo_context.get_registry", lambda: FakeRegistry())
    result = await run_repo_intent("grep", "nonexistent_term", "sess1")
    assert result == ""
