import pytest
import respx
from httpx import Response

from tools.google.contacts_tool import ContactsTool

LIST = "https://people.googleapis.com/v1/people/me/connections"
SEARCH = "https://people.googleapis.com/v1/people:searchContacts"


@pytest.mark.asyncio
async def test_query_returns_error_when_not_connected(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return {"error": "No Google connector configured for this account — connect Google first (Contacts needs it)."}

    monkeypatch.setattr("tools.google.contacts_tool.get_google_token", fake_get_token)
    result = await ContactsTool().query("list_contacts")
    assert "connect Google first" in result["error"]


@pytest.mark.asyncio
async def test_list_contacts_summarizes_each_person(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.contacts_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(LIST).mock(return_value=Response(200, json={"connections": [
            {"names": [{"displayName": "Jane Doe"}], "emailAddresses": [{"value": "jane@x.com"}],
             "phoneNumbers": [{"value": "+27123456789"}]},
        ]}))
        result = await ContactsTool().query("list_contacts")

    assert result == {"contacts": [{"name": "Jane Doe", "emails": ["jane@x.com"], "phones": ["+27123456789"]}]}


@pytest.mark.asyncio
async def test_search_contacts_requires_a_query(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.contacts_tool.get_google_token", fake_get_token)
    result = await ContactsTool().query("search_contacts")
    assert result == {"error": "query required"}


@pytest.mark.asyncio
async def test_search_contacts_returns_matches(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.contacts_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(SEARCH).mock(return_value=Response(200, json={"results": [
            {"person": {"names": [{"displayName": "Bob Smith"}], "emailAddresses": [], "phoneNumbers": []}},
        ]}))
        result = await ContactsTool().query("search_contacts", query="Bob")

    assert result == {"contacts": [{"name": "Bob Smith", "emails": [], "phones": []}]}


@pytest.mark.asyncio
async def test_unknown_action_returns_a_clear_error(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.contacts_tool.get_google_token", fake_get_token)
    result = await ContactsTool().query("delete_contact")
    assert "Unknown contacts action" in result["error"]
