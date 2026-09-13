from config import settings


class CalendarTool:
    """
    Google Calendar read/write, gated by ALLOW_EDITS permission in the registry.

    Not wired up to a real OAuth flow yet — Calendar's API needs a refresh-token
    dance that's out of scope for the AWS cost migration this file was added to
    unblock (tools/registry.py referenced this module but it didn't exist,
    which crashed get_registry() on first use). Returns a clear error instead
    of silently doing nothing or pretending to succeed.
    """

    async def query(self, action: str, **kwargs) -> dict:
        if not settings.GOOGLE_CALENDAR_CREDS:
            return {"error": "GOOGLE_CALENDAR_CREDS not configured"}
        return {
            "error": "Google Calendar integration not implemented",
            "action": action,
        }
