import datetime

import httpx

from tools.google._auth import get_google_token

_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class CalendarTool:
    """Real Google Calendar read/write (Calendar API v3), replacing the
    permanent stub that used to live here — that version only ever
    checked for a static credentials file path and returned "not
    implemented" unconditionally. Needs a Google OAuth connector for the
    account (see gateway/google_oauth.py), not a service-account file."""

    async def query(self, action: str, account_id: str = "owner", **kwargs) -> dict:
        token = await get_google_token(account_id, "Calendar")
        if isinstance(token, dict):
            return token
        headers = {"Authorization": f"Bearer {token}"}

        if action == "list_events":
            return await self._list_events(headers, kwargs)
        if action == "create_event":
            return await self._create_event(headers, kwargs)
        if action == "update_event":
            return await self._update_event(headers, kwargs)
        if action == "delete_event":
            return await self._delete_event(headers, kwargs)
        return {"error": f"Unknown calendar action: {action}"}

    async def _list_events(self, headers: dict, kwargs: dict) -> dict:
        params = {
            "maxResults": kwargs.get("max_results", 10),
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": kwargs.get("time_min") or _now_rfc3339(),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_BASE, params=params, headers=headers)
        if r.status_code != 200:
            return {"error": f"Calendar API error {r.status_code}: {r.text[:300]}"}
        data = r.json()
        return {"events": [
            {
                "id": e["id"],
                "summary": e.get("summary", "(no title)"),
                "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
                "end": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date"),
                "location": e.get("location"),
            }
            for e in data.get("items", [])
        ]}

    async def _create_event(self, headers: dict, kwargs: dict) -> dict:
        if not kwargs.get("start") or not kwargs.get("end"):
            return {"error": "start and end (RFC3339 datetimes) required"}
        body = {
            "summary": kwargs.get("summary", "(untitled)"),
            "start": {"dateTime": kwargs["start"]},
            "end": {"dateTime": kwargs["end"]},
        }
        if kwargs.get("description"):
            body["description"] = kwargs["description"]
        if kwargs.get("location"):
            body["location"] = kwargs["location"]
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(_BASE, json=body, headers=headers)
        if r.status_code not in (200, 201):
            return {"error": f"Calendar API error {r.status_code}: {r.text[:300]}"}
        data = r.json()
        return {"id": data["id"], "summary": data.get("summary"), "htmlLink": data.get("htmlLink")}

    async def _update_event(self, headers: dict, kwargs: dict) -> dict:
        event_id = kwargs.get("event_id")
        if not event_id:
            return {"error": "event_id required"}
        body = {k: v for k, v in {
            "summary": kwargs.get("summary"),
            "description": kwargs.get("description"),
            "location": kwargs.get("location"),
        }.items() if v is not None}
        if kwargs.get("start"):
            body["start"] = {"dateTime": kwargs["start"]}
        if kwargs.get("end"):
            body["end"] = {"dateTime": kwargs["end"]}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.patch(f"{_BASE}/{event_id}", json=body, headers=headers)
        if r.status_code != 200:
            return {"error": f"Calendar API error {r.status_code}: {r.text[:300]}"}
        data = r.json()
        return {"id": data["id"], "summary": data.get("summary")}

    async def _delete_event(self, headers: dict, kwargs: dict) -> dict:
        event_id = kwargs.get("event_id")
        if not event_id:
            return {"error": "event_id required"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.delete(f"{_BASE}/{event_id}", headers=headers)
        if r.status_code not in (200, 204):
            return {"error": f"Calendar API error {r.status_code}: {r.text[:300]}"}
        return {"deleted": event_id}


def _now_rfc3339() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
