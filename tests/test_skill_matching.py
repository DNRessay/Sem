import pytest

from pipeline.bootstrap import Bootstrap


class FakeStore:
    def __init__(self, skills):
        self._skills = skills

    async def list_skills(self, enabled_only: bool = False):
        rows = self._skills
        if enabled_only:
            rows = [s for s in rows if s["enabled"]]
        return rows


@pytest.mark.asyncio
async def test_skills_context_always_lists_enabled_skills_by_name_and_description(monkeypatch):
    skills = [{"name": "Deploy checklist", "description": "Use when deploying to production",
               "triggers": ["deploy"], "content": "Run tests first.", "enabled": True}]

    async def fake_get_store():
        return FakeStore(skills)

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    # No trigger keyword in this query — the catalog should still show up.
    block = await bootstrap._skills_context("what's the weather today?")
    assert "<available_skills>" in block
    assert "Deploy checklist: Use when deploying to production" in block
    assert "<active_skills>" not in block  # not triggered, so full content isn't loaded


@pytest.mark.asyncio
async def test_skills_context_loads_full_content_when_trigger_matches(monkeypatch):
    skills = [{"name": "Deploy checklist", "description": "Use when deploying",
               "triggers": ["deploy", "release"], "content": "Run tests first.", "enabled": True}]

    async def fake_get_store():
        return FakeStore(skills)

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    block = await bootstrap._skills_context("how do I deploy this?")
    assert "<available_skills>" in block
    assert "<active_skills>" in block
    assert "Run tests first." in block


@pytest.mark.asyncio
async def test_skills_context_ignores_disabled_skills(monkeypatch):
    skills = [{"name": "Off", "description": "should not appear", "triggers": ["deploy"],
               "content": "x", "enabled": False}]

    async def fake_get_store():
        return FakeStore(skills)

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    block = await bootstrap._skills_context("deploy now")
    assert block == ""


@pytest.mark.asyncio
async def test_skills_context_returns_empty_when_no_skills_exist(monkeypatch):
    async def fake_get_store():
        return FakeStore([])

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    assert await bootstrap._skills_context("anything") == ""
