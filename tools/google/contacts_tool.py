import httpx

from tools.google._auth import get_google_token

_BASE = "https://people.googleapis.com/v1/people/me/connections"
_SEARCH = "https://people.googleapis.com/v1/people:searchContacts"


class ContactsTool:
    """Google Contacts read via the People API — read-only, matching what
    was actually asked for ("will get us contacts"; no write/edit request
    was made for this one, unlike Calendar and Gmail)."""

    async def query(self, action: str, account_id: str = "owner", **kwargs) -> dict:
        token = await get_google_token(account_id, "Contacts")
        if isinstance(token, dict):
            return token
        headers = {"Authorization": f"Bearer {token}"}

        if action == "list_contacts":
            return await self._list_contacts(headers, kwargs)
        if action == "search_contacts":
            return await self._search_contacts(headers, kwargs)
        return {"error": f"Unknown contacts action: {action}"}

    async def _list_contacts(self, headers: dict, kwargs: dict) -> dict:
        params = {
            "personFields": "names,emailAddresses,phoneNumbers",
            "pageSize": kwargs.get("max_results", 50),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_BASE, params=params, headers=headers)
        if r.status_code != 200:
            return {"error": f"Contacts API error {r.status_code}: {r.text[:300]}"}
        return {"contacts": [_summarize_person(p) for p in r.json().get("connections", [])]}

    async def _search_contacts(self, headers: dict, kwargs: dict) -> dict:
        query = kwargs.get("query", "")
        if not query:
            return {"error": "query required"}
        params = {"query": query, "readMask": "names,emailAddresses,phoneNumbers"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_SEARCH, params=params, headers=headers)
        if r.status_code != 200:
            return {"error": f"Contacts API error {r.status_code}: {r.text[:300]}"}
        return {"contacts": [_summarize_person(m.get("person", {})) for m in r.json().get("results", [])]}


def _summarize_person(p: dict) -> dict:
    names = p.get("names") or [{}]
    emails = [e.get("value") for e in (p.get("emailAddresses") or [])]
    phones = [ph.get("value") for ph in (p.get("phoneNumbers") or [])]
    return {"name": names[0].get("displayName"), "emails": emails, "phones": phones}
