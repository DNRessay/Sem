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
async def test_match_skills_injects_content_when_trigger_present(monkeypatch):
    skills = [{"name": "Deploy checklist", "triggers": ["deploy", "release"],
               "content": "Run tests first.", "enabled": True}]

    async def fake_get_store():
        return FakeStore(skills)

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    block = await bootstrap._match_skills("how do I deploy this?")
    assert "Deploy checklist" in block
    assert "Run tests first." in block


@pytest.mark.asyncio
async def test_match_skills_returns_empty_when_no_trigger_matches(monkeypatch):
    skills = [{"name": "Deploy checklist", "triggers": ["deploy"],
               "content": "Run tests first.", "enabled": True}]

    async def fake_get_store():
        return FakeStore(skills)

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    block = await bootstrap._match_skills("what's the weather today?")
    assert block == ""


@pytest.mark.asyncio
async def test_match_skills_ignores_disabled_skills(monkeypatch):
    skills = [{"name": "Off", "triggers": ["deploy"], "content": "x", "enabled": False}]

    async def fake_get_store():
        return FakeStore(skills)

    monkeypatch.setattr("pipeline.bootstrap.get_store", fake_get_store)
    bootstrap = Bootstrap()

    block = await bootstrap._match_skills("deploy now")
    assert block == ""
