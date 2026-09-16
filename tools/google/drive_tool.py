import json

import httpx

from tools.google._auth import get_google_token

_FILES = "https://www.googleapis.com/drive/v3/files"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


class DriveTool:
    """Google Drive via the `drive.file` scope only — the app can see and
    read only files it created itself (or that the user explicitly picked
    through Google's own file picker, which isn't wired up here). That's a
    deliberate privacy-minimizing choice over the much broader `drive`
    scope (full read/write access to every file in the user's Drive), and
    maps directly onto "notes": create_note/append_note/read_file/
    list_files all only ever touch plain-text files SEMBLANCE made."""

    async def query(self, action: str, account_id: str = "owner", **kwargs) -> dict:
        token = await get_google_token(account_id, "Drive")
        if isinstance(token, dict):
            return token
        headers = {"Authorization": f"Bearer {token}"}

        if action == "list_files":
            return await self._list_files(headers, kwargs)
        if action == "read_file":
            return await self._read_file(headers, kwargs)
        if action == "create_note":
            return await self._create_note(headers, kwargs)
        if action == "append_note":
            return await self._append_note(headers, kwargs)
        return {"error": f"Unknown drive action: {action}"}

    async def _list_files(self, headers: dict, kwargs: dict) -> dict:
        params = {"pageSize": kwargs.get("max_results", 20), "fields": "files(id,name,mimeType,modifiedTime)"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_FILES, params=params, headers=headers)
        if r.status_code != 200:
            return {"error": f"Drive API error {r.status_code}: {r.text[:300]}"}
        return {"files": r.json().get("files", [])}

    async def _read_file(self, headers: dict, kwargs: dict) -> dict:
        file_id = kwargs.get("file_id")
        if not file_id:
            return {"error": "file_id required"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{_FILES}/{file_id}", params={"alt": "media"}, headers=headers)
        if r.status_code != 200:
            return {"error": f"Drive API error {r.status_code}: {r.text[:300]}"}
        return {"file_id": file_id, "content": r.text}

    async def _create_note(self, headers: dict, kwargs: dict) -> dict:
        title = kwargs.get("title", "Untitled note")
        content = kwargs.get("content", "")
        metadata = {"name": title, "mimeType": "text/plain"}
        files = {
            "metadata": (None, json.dumps(metadata), "application/json"),
            "file": (None, content, "text/plain"),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{_UPLOAD}?uploadType=multipart", headers=headers, files=files)
        if r.status_code not in (200, 201):
            return {"error": f"Drive API error {r.status_code}: {r.text[:300]}"}
        data = r.json()
        return {"file_id": data["id"], "title": title}

    async def _append_note(self, headers: dict, kwargs: dict) -> dict:
        file_id = kwargs.get("file_id")
        addition = kwargs.get("content", "")
        if not file_id:
            return {"error": "file_id required"}
        existing = await self._read_file(headers, {"file_id": file_id})
        if existing.get("error"):
            return existing
        new_content = existing["content"] + "\n" + addition
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.patch(
                f"{_UPLOAD}/{file_id}?uploadType=media",
                headers={**headers, "Content-Type": "text/plain"},
                content=new_content.encode(),
            )
        if r.status_code != 200:
            return {"error": f"Drive API error {r.status_code}: {r.text[:300]}"}
        return {"file_id": file_id, "appended": True}
