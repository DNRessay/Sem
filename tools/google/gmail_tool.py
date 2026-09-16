import base64
import email.mime.text

import httpx

from tools.google._auth import get_google_token

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailTool:
    """Real Gmail read + send (Gmail API v1) — deliberately read + send
    only, not full modify/delete/trash, matching exactly what was asked
    for and keeping the OAuth consent screen's scope list as narrow as it
    can be."""

    async def query(self, action: str, account_id: str = "owner", **kwargs) -> dict:
        token = await get_google_token(account_id, "Gmail")
        if isinstance(token, dict):
            return token
        headers = {"Authorization": f"Bearer {token}"}

        if action == "list_messages":
            return await self._list_messages(headers, kwargs)
        if action == "read_message":
            return await self._read_message(headers, kwargs)
        if action == "send_message":
            return await self._send_message(headers, kwargs)
        return {"error": f"Unknown gmail action: {action}"}

    async def _list_messages(self, headers: dict, kwargs: dict) -> dict:
        params = {"maxResults": kwargs.get("max_results", 10)}
        if kwargs.get("query"):
            params["q"] = kwargs["query"]
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{_BASE}/messages", params=params, headers=headers)
            if r.status_code != 200:
                return {"error": f"Gmail API error {r.status_code}: {r.text[:300]}"}
            ids = [m["id"] for m in r.json().get("messages", [])]

            # One extra call per message for a real subject/from/snippet
            # instead of bare IDs — capped at max_results (a handful for a
            # normal "what's in my inbox" ask), not a full mailbox crawl.
            messages = []
            for mid in ids:
                mr = await client.get(
                    f"{_BASE}/messages/{mid}",
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                    headers=headers,
                )
                if mr.status_code == 200:
                    messages.append(_summarize_message(mr.json()))
        return {"messages": messages}

    async def _read_message(self, headers: dict, kwargs: dict) -> dict:
        message_id = kwargs.get("message_id")
        if not message_id:
            return {"error": "message_id required"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{_BASE}/messages/{message_id}", params={"format": "full"}, headers=headers)
        if r.status_code != 200:
            return {"error": f"Gmail API error {r.status_code}: {r.text[:300]}"}
        data = r.json()
        summary = _summarize_message(data)
        summary["body"] = _extract_body(data.get("payload") or {})
        return summary

    async def _send_message(self, headers: dict, kwargs: dict) -> dict:
        to = kwargs.get("to")
        if not to:
            return {"error": "to required"}
        subject = kwargs.get("subject", "")
        body = kwargs.get("body", "")
        msg = email.mime.text.MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{_BASE}/messages/send", json={"raw": raw}, headers=headers)
        if r.status_code not in (200, 202):
            return {"error": f"Gmail API error {r.status_code}: {r.text[:300]}"}
        data = r.json()
        return {"id": data.get("id"), "sent_to": to, "subject": subject}


def _summarize_message(data: dict) -> dict:
    headers_list = (data.get("payload") or {}).get("headers", [])
    h = {x["name"]: x["value"] for x in headers_list}
    return {
        "id": data.get("id"),
        "from": h.get("From"),
        "subject": h.get("Subject"),
        "date": h.get("Date"),
        "snippet": data.get("snippet"),
    }


def _extract_body(payload: dict) -> str:
    """Gmail nests the actual body under `parts` for a multipart message,
    or directly in the payload for a plain one — walks both shapes for
    the first text/plain part it finds."""
    if payload.get("mimeType") == "text/plain" and (payload.get("body") or {}).get("data"):
        return _b64_decode(payload["body"]["data"])
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain" and (part.get("body") or {}).get("data"):
            return _b64_decode(part["body"]["data"])
    for part in payload.get("parts") or []:
        nested = _extract_body(part)
        if nested:
            return nested
    return ""


def _b64_decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
