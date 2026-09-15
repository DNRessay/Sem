import pytest
from fastapi.testclient import TestClient

from gateway.auth import require_account
from main import app


class FakeBootstrap:
    def __init__(self, trust_mode="AUTO", tau_context=""):
        pass

    async def run(self, query, session_id, history, images=None, display_query=None, assistant_prefix=""):
        yield "ok"


class _NoopStore:
    """Minimal store double for tests that only need get_store() to resolve
    to something — a blocked/failed tool branch now always logs an agent
    event, even when nothing else in the test cares about persistence."""

    async def save_agent_event(self, session_id, agent, action):
        pass


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[require_account] = lambda: {"account_id": "owner", "role": "owner"}

    async def fake_observe_and_inject(session_id, query, history):
        return ""

    async def fake_generate_title(user_msg, reply):
        # Default no-op — a real (unmocked) Groq call here would be slow/
        # blocked in tests; individual tests override this to check title
        # generation specifically.
        return ""

    monkeypatch.setattr("gateway.router._tau.observe_and_inject", fake_observe_and_inject)
    monkeypatch.setattr("gateway.router.Bootstrap", FakeBootstrap)
    monkeypatch.setattr("gateway.router.generate_title", fake_generate_title)
    yield TestClient(app)
    app.dependency_overrides.pop(require_account, None)


def test_chat_with_no_message_and_no_attachments_returns_400(client):
    resp = client.post("/chat", json={"message": "", "session_id": "sess1"})
    assert resp.status_code == 400


def test_chat_with_an_attachment_and_no_typed_message_still_succeeds(client):
    """Attaching a file with no typed comment ("here's a PDF, look at it")
    used to 400 with "message required" even though the attachment alone
    gives the model plenty to respond to — a real user hit this exact
    case."""
    resp = client.post("/chat", json={
        "message": "",
        "session_id": "sess1",
        "attachments": [{"name": "notes.txt", "content": "some file content"}],
    })
    assert resp.status_code == 200


def test_url_shaped_text_inside_an_attachment_does_not_trigger_a_fetch(client, monkeypatch):
    """A regex literal like https://[a-zA-Z0-9.-]*\\.on\\.aws sitting inside an
    attached file (a workflow script, a README example, anything) used to get
    scanned by detect_web_intent along with the rest of the augmented message
    and treated as "fetch this URL" — hijacking the user's real question and
    hanging on a garbage host until the fetch tool's own timeout. Web-intent
    detection must only look at what the user actually typed."""
    calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        calls.append((kind, target))
        return ""

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)

    resp = client.post("/chat", json={
        "message": "What's in here",
        "session_id": "sess1",
        "attachments": [
            {
                "name": "cloudflare-pages.yml",
                "content": "found=$(grep -o 'https://[a-zA-Z0-9.-]*\\.on\\.aws' dist/assets/*.js || true)",
            },
        ],
    })
    assert resp.status_code == 200
    assert calls == []


def test_a_url_the_user_actually_typed_still_triggers_a_fetch(client, monkeypatch):
    calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        calls.append((kind, target))
        return ""

    async def fake_get_store():
        return _NoopStore()

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={
        "message": "check out https://example.com/page",
        "session_id": "sess1",
    })
    assert resp.status_code == 200
    assert calls == [("fetch", "https://example.com/page")]


def test_web_search_enabled_defaults_to_true_when_omitted(client, monkeypatch):
    calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        calls.append((kind, target))
        return ""

    async def fake_get_store():
        return _NoopStore()

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "check out https://example.com/page", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("fetch", "https://example.com/page")]


def test_web_search_disabled_skips_detection_entirely(client, monkeypatch):
    """The attach menu's "Web search" toggle — off means detect_web_intent
    never even runs for this turn, not just that its result gets ignored."""
    calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        calls.append((kind, target))
        return ""

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)

    resp = client.post("/chat", json={
        "message": "check out https://example.com/page",
        "session_id": "sess1",
        "web_search_enabled": False,
    })
    assert resp.status_code == 200
    assert calls == []
    assert "ok" in resp.text  # FakeBootstrap's fixed reply — the normal flow ran instead


def test_repo_intent_takes_priority_over_web_intent(client, monkeypatch):
    """'search the repo for X' contains the bare word 'search', which alone
    would trigger a web search — but repo phrasing is more specific and must
    win, so this calls run_repo_intent and never run_web_intent."""
    web_calls = []
    repo_calls = []

    async def fake_run_web_intent(kind, target, session_id=None):
        web_calls.append((kind, target))
        return ""

    async def fake_run_repo_intent(target, session_id):
        repo_calls.append((target, session_id))
        return ""

    async def fake_get_store():
        return _NoopStore()

    monkeypatch.setattr("gateway.router.run_web_intent", fake_run_web_intent)
    monkeypatch.setattr("gateway.router.run_repo_intent", fake_run_repo_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={
        "message": "search the repo for save_turn",
        "session_id": "sess1",
    })
    assert resp.status_code == 200
    assert web_calls == []
    assert repo_calls == [("save_turn", "sess1")]


def test_readme_question_bypasses_the_llm_and_streams_the_raw_file(client, monkeypatch):
    """A file read never reaches bootstrap.run/the LLM at all — see
    pipeline.repo_context.fetch_repo_file_raw's docstring: reproducing exact
    content through a max_tokens-limited model reliably truncates larger
    files, and there's no reasoning involved in the task anyway."""
    calls = []

    async def fake_fetch_repo_file_raw(target, session_id):
        calls.append((target, session_id))
        return ("README.md", "hello world")

    class RecordingStore:
        def __init__(self):
            self.turns = []
            self.memories = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            self.memories.append((session_id, content))

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.fetch_repo_file_raw", fake_fetch_repo_file_raw)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "what's in the readme", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("README.md", "sess1")]
    assert "hello world" in resp.text  # streamed directly, not through the LLM
    assert ("sess1", "user", "what's in the readme") in store.turns
    assert any(role == "assistant" and "hello world" in content for _, role, content in store.turns)
    # only the query gets embedded — the reply is tool-derived, matches
    # Bootstrap.run's skip-embedding-tool-output behavior
    assert store.memories == [("sess1", "what's in the readme")]


def test_repo_read_falls_back_to_normal_flow_when_fetch_fails(client, monkeypatch):
    """No active repo, or the read failed — falls through to the ordinary
    LLM flow (with no repo context folded in) rather than the request just
    going silent."""
    async def fake_fetch_repo_file_raw(target, session_id):
        return None

    async def fake_get_store():
        return _NoopStore()

    monkeypatch.setattr("gateway.router.fetch_repo_file_raw", fake_fetch_repo_file_raw)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "what's in the readme", "session_id": "sess1"})
    assert resp.status_code == 200
    assert "ok" in resp.text  # FakeBootstrap's fixed reply — the normal flow ran


def test_first_turn_generates_and_persists_a_session_title(client, monkeypatch):
    """The header used to just show the raw session ID and the sidebar the
    literal first message — this generates a real short title instead, but
    only once, on a session's first turn (no history yet)."""
    calls = []

    async def fake_generate_title(user_msg, reply):
        calls.append((user_msg, reply))
        return "Chess opening strategy"

    class RecordingStore:
        def __init__(self):
            self.titles = {}

        async def set_session_title(self, session_id, title):
            self.titles[session_id] = title

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.generate_title", fake_generate_title)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "tell me about the Nimzo-Larsen", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("tell me about the Nimzo-Larsen", "ok")]  # "ok" is FakeBootstrap's fixed reply
    assert store.titles == {"sess1": "Chess opening strategy"}
    assert '"title": "Chess opening strategy"' in resp.text


def test_later_turns_do_not_regenerate_the_title(client, monkeypatch):
    calls = []

    async def fake_generate_title(user_msg, reply):
        calls.append((user_msg, reply))
        return "Should not be called"

    monkeypatch.setattr("gateway.router.generate_title", fake_generate_title)

    resp = client.post("/chat", json={
        "message": "and what about the Reti?",
        "session_id": "sess1",
        "history": [
            {"role": "user", "content": "tell me about the Nimzo-Larsen"},
            {"role": "assistant", "content": "It's a hypermodern opening..."},
        ],
    })
    assert resp.status_code == 200
    assert calls == []


def test_plan_intent_bypasses_the_llm_and_streams_the_formatted_plan(client, monkeypatch):
    """Step 7 (sub-agent delegation) reachable from a real chat message: a
    "make a plan for X" message routes through run_plan_intent (CablesMan
    -> PlanAgent) instead of Bootstrap/the main LLM call, same bypass shape
    as the repo "read" intent."""
    calls = []

    async def fake_run_plan_intent(goal, session_id):
        calls.append((goal, session_id))
        return {"steps": [{"n": 1, "action": "set up the bot", "tool": "bash"}],
                "risks": [], "success_criteria": "bot is live"}

    class RecordingStore:
        def __init__(self):
            self.turns = []
            self.memories = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            self.memories.append((session_id, content))

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.run_plan_intent", fake_run_plan_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "make a plan for launching the bot", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("make a plan for launching the bot", "sess1")]
    assert "set up the bot" in resp.text
    assert "bot is live" in resp.text
    assert ("sess1", "user", "make a plan for launching the bot") in store.turns
    assert store.memories == [("sess1", "make a plan for launching the bot")]


def test_plan_intent_falls_back_to_normal_flow_when_no_plan_comes_back(client, monkeypatch):
    async def fake_run_plan_intent(goal, session_id):
        return {}

    monkeypatch.setattr("gateway.router.run_plan_intent", fake_run_plan_intent)

    resp = client.post("/chat", json={"message": "make a plan for launching the bot", "session_id": "sess1"})
    assert resp.status_code == 200
    assert "ok" in resp.text  # FakeBootstrap's fixed reply — the normal flow ran


def test_explore_code_intent_bypasses_the_llm_and_streams_the_matches(client, monkeypatch):
    """"search the code for X" routes through run_explore_intent (CablesMan
    -> ExploreAgent, scope=code) — no LLM call involved at all."""
    calls = []

    async def fake_run_explore_intent(term, session_id):
        calls.append((term, session_id))
        return [{"file": "pipeline/query_engine.py", "line": 25, "content": "_DEFAULT_MAX_TOKENS = 800"}]

    class RecordingStore:
        def __init__(self):
            self.turns = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            pass

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.run_explore_intent", fake_run_explore_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "search the code for _DEFAULT_MAX_TOKENS", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("_DEFAULT_MAX_TOKENS", "sess1")]
    assert "query_engine.py" in resp.text
    assert ("sess1", "user", "search the code for _DEFAULT_MAX_TOKENS") in store.turns


def test_explore_code_intent_does_not_fire_on_repo_grep_phrasing(client, monkeypatch):
    """"search the codebase for X" belongs to repo_intent (an externally
    attached repo), checked first — explore_intent must not also match."""
    explore_calls = []
    repo_calls = []

    async def fake_run_explore_intent(term, session_id):
        explore_calls.append(term)
        return []

    async def fake_run_repo_intent(target, session_id):
        repo_calls.append(target)
        return ""

    async def fake_get_store():
        return _NoopStore()

    monkeypatch.setattr("gateway.router.run_explore_intent", fake_run_explore_intent)
    monkeypatch.setattr("gateway.router.run_repo_intent", fake_run_repo_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "search the codebase for TODO", "session_id": "sess1"})
    assert resp.status_code == 200
    assert explore_calls == []
    assert repo_calls == ["TODO"]


def test_guide_intent_bypasses_the_llm_and_streams_the_answer(client, monkeypatch):
    """"what can you do" routes through run_guide_intent (CablesMan ->
    GuideAgent) — a pure string lookup, no LLM call involved at all."""
    calls = []

    async def fake_run_guide_intent(query, session_id):
        calls.append((query, session_id))
        return "I can plan, search my own code, and remember things."

    class RecordingStore:
        def __init__(self):
            self.turns = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            pass

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.run_guide_intent", fake_run_guide_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "what can you do", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("what can you do", "sess1")]
    assert "remember things" in resp.text
    assert ("sess1", "user", "what can you do") in store.turns


def test_buddy_intent_bypasses_the_llm_and_streams_the_status(client, monkeypatch):
    """"buddy" (bare, whole-message) routes through run_buddy_intent
    (CablesMan -> BuddyAgent) — no LLM call involved."""
    calls = []

    async def fake_run_buddy_intent(intent, session_id):
        calls.append((intent, session_id))
        return {"name": "Sparkcub_1", "species": "Sparkcub", "rarity": "Rare", "mood": "calm",
                "level": 1, "xp": 0, "xp_next": 100, "hp": 100,
                "stats": {"energy": 80, "happiness": 90, "focus": 70}}

    class RecordingStore:
        def __init__(self):
            self.turns = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            pass

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.run_buddy_intent", fake_run_buddy_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "buddy", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [({"action": "status"}, "sess1")]
    assert "Sparkcub_1" in resp.text
    assert ("sess1", "user", "buddy") in store.turns


def test_memory_search_intent_bypasses_the_llm_and_streams_grounded_results(client, monkeypatch):
    """"when did I ask about X" routes through run_memory_search_intent —
    a real cross-session DB search, never the model guessing from its own
    session-scoped context (the exact wrong-answer case this fixes)."""
    calls = []

    async def fake_run_memory_search_intent(intent, session_id):
        calls.append((intent, session_id))
        return {
            "term": "Mandela", "mode": "when",
            "matches": [{"session_id": "session_old", "role": "user", "content": "Who is Nelson Mandela",
                         "created_at": 1000.0, "title": "Who is Nelson Mandela"}],
        }

    class RecordingStore:
        def __init__(self):
            self.turns = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            pass

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.run_memory_search_intent", fake_run_memory_search_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "When did I ask u about Mandela", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [({"mode": "when", "term": "Mandela", "window": None}, "sess1")]
    assert "Who is Nelson Mandela" in resp.text
    assert ("sess1", "user", "When did I ask u about Mandela") in store.turns


def test_bash_intent_bypasses_the_llm_and_streams_the_command_output(client, monkeypatch):
    """Step 5 (tool execution) reachable directly from chat, not just from
    a sub-agent: "run bash: X" routes through run_bash_intent instead of
    Bootstrap/the main LLM call, same bypass shape as the repo "read" and
    plan/explore intents."""
    calls = []

    async def fake_run_bash_intent(command, session_id):
        calls.append((command, session_id))
        return {"blocked": False, "stdout": "hello\n", "stderr": "", "exit_code": 0}

    class RecordingStore:
        def __init__(self):
            self.turns = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            pass

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.run_bash_intent", fake_run_bash_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "run bash: echo hello", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == [("echo hello", "sess1")]
    assert "hello" in resp.text
    assert "Exit code: 0" in resp.text
    assert ("sess1", "user", "run bash: echo hello") in store.turns


def test_bash_intent_falls_back_to_normal_flow_when_formatting_yields_nothing(client, monkeypatch):
    """format_bash_result only ever returns "" for a non-dict result — in
    practice run_bash_intent always returns a dict (even a blocked/errored
    command formats to a real message), so this exercises the defensive
    fallback path rather than a scenario that happens in normal use."""
    async def fake_run_bash_intent(command, session_id):
        return None

    monkeypatch.setattr("gateway.router.run_bash_intent", fake_run_bash_intent)

    resp = client.post("/chat", json={"message": "run bash: echo hello", "session_id": "sess1"})
    assert resp.status_code == 200
    assert "ok" in resp.text  # FakeBootstrap's fixed reply — the normal flow ran


def test_continue_intent_bypasses_the_llm_and_advances_the_plan(client, monkeypatch):
    """A bare "continue" routes through run_continue_intent instead of
    Bootstrap/the main LLM call — same bypass shape as every other
    deterministic intent in this router."""
    calls = []

    async def fake_run_continue_intent(session_id):
        calls.append(session_id)
        return {"done": False, "step_n": 1, "action": "list files", "command": "ls -la",
                "outcome": "a.py\nb.py", "remaining": 1, "total": 2}

    class RecordingStore:
        def __init__(self):
            self.turns = []

        async def save_turn(self, session_id, role, content):
            self.turns.append((session_id, role, content))

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            pass

        async def save_agent_event(self, session_id, agent, action):
            pass

    store = RecordingStore()

    async def fake_get_store():
        return store

    monkeypatch.setattr("gateway.router.run_continue_intent", fake_run_continue_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "continue", "session_id": "sess1"})
    assert resp.status_code == 200
    assert calls == ["sess1"]
    assert "Step 1 of 2" in resp.text
    assert "ls -la" in resp.text
    assert ("sess1", "user", "continue") in store.turns


def test_continue_intent_never_falls_back_to_the_normal_flow(client, monkeypatch):
    """Even with no active plan, "continue" alone has nothing else for
    Bootstrap to meaningfully respond to — the deterministic "no active
    plan" message is always the right answer, so this never falls
    through the way plan/explore do on failure."""
    async def fake_run_continue_intent(session_id):
        return {"done": None}

    class RecordingStore:
        async def save_turn(self, session_id, role, content):
            pass

        async def save_memory(self, session_id, content, salience=0.5, embedding=None):
            pass

        async def save_agent_event(self, session_id, agent, action):
            pass

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.run_continue_intent", fake_run_continue_intent)
    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.post("/chat", json={"message": "continue", "session_id": "sess1"})
    assert resp.status_code == 200
    assert "no active plan" in resp.text.lower()
    assert "ok" not in resp.text  # FakeBootstrap's fixed reply must NOT have run


def test_status_endpoint_returns_the_latest_agent_event(client, monkeypatch):
    class RecordingStore:
        async def get_latest_agent_event(self, session_id):
            assert session_id == "sess1"
            return {"agent": "plan", "action": "complete", "ts": 12345}

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.get("/status/sess1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess1"
    assert body["event"] == {"agent": "plan", "action": "complete", "ts": 12345}


def test_status_endpoint_returns_no_event_for_a_quiet_session(client, monkeypatch):
    class RecordingStore:
        async def get_latest_agent_event(self, session_id):
            return None

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.get("/status/sess1")
    assert resp.status_code == 200
    assert resp.json()["event"] is None


def test_status_events_endpoint_returns_events_since_a_cursor(client, monkeypatch):
    class RecordingStore:
        async def get_recent_agent_events(self, session_id, since_id=0, limit=30):
            assert session_id == "sess1"
            assert since_id == 5
            assert limit == 30
            return [{"id": 6, "agent": "web", "action": "ok:Searching web", "ts": 12345}]

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.get("/status/sess1/events?since=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess1"
    assert body["events"] == [{"id": 6, "agent": "web", "action": "ok:Searching web", "ts": 12345}]


def test_status_events_endpoint_defaults_since_to_zero(client, monkeypatch):
    class RecordingStore:
        async def get_recent_agent_events(self, session_id, since_id=0, limit=30):
            assert since_id == 0
            return []

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.get("/status/sess1/events")
    assert resp.status_code == 200
    assert resp.json()["events"] == []


def test_delete_session_endpoint_calls_db_delete(client, monkeypatch):
    calls = []

    class RecordingStore:
        async def delete_session(self, session_id):
            calls.append(session_id)

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.delete("/sessions/sess1")
    assert resp.status_code == 200
    assert resp.json() == {"session_id": "sess1", "deleted": True}
    assert calls == ["sess1"]


def test_rename_session_endpoint_sets_title(client, monkeypatch):
    calls = []

    class RecordingStore:
        async def set_session_title(self, session_id, title):
            calls.append((session_id, title))

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.patch("/sessions/sess1", json={"title": "Fixed the buddy XP bug"})
    assert resp.status_code == 200
    assert resp.json() == {"session_id": "sess1", "title": "Fixed the buddy XP bug"}
    assert calls == [("sess1", "Fixed the buddy XP bug")]


def test_rename_session_endpoint_requires_a_nonempty_title(client, monkeypatch):
    resp = client.patch("/sessions/sess1", json={"title": "   "})
    assert resp.status_code == 400


def test_rename_session_endpoint_truncates_long_titles(client, monkeypatch):
    calls = []

    class RecordingStore:
        async def set_session_title(self, session_id, title):
            calls.append(title)

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("gateway.router.get_store", fake_get_store)

    resp = client.patch("/sessions/sess1", json={"title": "x" * 200})
    assert resp.status_code == 200
    assert len(resp.json()["title"]) == 80
    assert len(calls[0]) == 80
