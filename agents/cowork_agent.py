from datetime import datetime, timedelta, timezone

from agents.tool_loop import ToolLoopAgent, fn_tool
from config import settings
from storage.neon_store import get_store
from tools import gemini_media
from tools.google.calendar_tool import CalendarTool
from tools.google.contacts_tool import ContactsTool
from tools.google.drive_tool import DriveTool
from tools.google.gmail_tool import GmailTool
from tools.web.fetch_tool import FetchTool
from tools.web.search import web_search

_SAST = timezone(timedelta(hours=2))

_SYSTEM = """You are Sem Co-work, SEMBLANCE's assistant for getting real work done: research, writing,
email, calendar, notes and images. It is {now} (South Africa time).

How to work:
- Work toward the outcome the user asked for, using tools as needed; don't stop at advice when you can do the task.
- Research with web_search, then fetch_url to read the best sources; say where facts came from.
- Long-form output (reports, drafts, plans) goes into a Drive note with drive_create_note, and you share the gist in chat.
- Sending email and creating calendar events never happen directly: gmail_send and calendar_create queue the
  action for the user to approve with one tap. Tell them it's waiting for approval.
- Finish with a short summary of what you did and anything waiting on the user.
You are SEMBLANCE running on open-weight models by default; never claim to be Claude, GPT or any other vendor's model."""

_S = {"type": "string"}
_I = {"type": "integer"}
TOOLS = {
    "web_search": fn_tool("web_search", "Search the web. Returns titles, URLs and snippets.", {"query": _S}, ["query"]),
    "fetch_url": fn_tool("fetch_url", "Read a web page as text.", {"url": _S}, ["url"]),
    "search_memory": fn_tool("search_memory", "Search the user's past SEMBLANCE conversations for a word or phrase.",
                             {"term": _S}, ["term"]),
    "gmail_search": fn_tool("gmail_search", "Search Gmail (Gmail search syntax, e.g. 'from:bank newer_than:7d').",
                            {"query": _S, "max_results": _I}, []),
    "gmail_read": fn_tool("gmail_read", "Read one email by id.", {"message_id": _S}, ["message_id"]),
    "gmail_send": fn_tool("gmail_send", "Queue an email for the user to approve and send.",
                          {"to": _S, "subject": _S, "body": _S}, ["to", "subject", "body"]),
    "calendar_list": fn_tool("calendar_list", "List upcoming calendar events from time_min (RFC3339, default now).",
                             {"time_min": _S, "max_results": _I}, []),
    "calendar_create": fn_tool(
        "calendar_create", "Queue a calendar event for the user to approve. start/end are RFC3339 with offset (+02:00).",
        {"summary": _S, "start": _S, "end": _S, "description": _S, "location": _S}, ["summary", "start", "end"],
    ),
    "drive_list": fn_tool("drive_list", "List the notes SEMBLANCE has saved in Google Drive.", {}, []),
    "drive_read": fn_tool("drive_read", "Read a Drive note by file id.", {"file_id": _S}, ["file_id"]),
    "drive_create_note": fn_tool("drive_create_note", "Save a new note/document to Google Drive.",
                                 {"title": _S, "content": _S}, ["title", "content"]),
    "drive_append_note": fn_tool("drive_append_note", "Append text to an existing Drive note.",
                                 {"file_id": _S, "content": _S}, ["file_id", "content"]),
    "set_reminder": fn_tool(
        "set_reminder", "Remind the user later. `when` is RFC3339 with offset (+02:00). Delivered in the app (and "
        "WhatsApp if set up) within ~15 minutes of that time.", {"message": _S, "when": _S}, ["message", "when"],
    ),
    "list_reminders": fn_tool("list_reminders", "List the user's upcoming reminders.", {}, []),
    "contacts_search": fn_tool("contacts_search", "Find a person in Google Contacts.", {"query": _S}, ["query"]),
    "generate_image": fn_tool(
        "generate_image", "Create an image with Gemini (Nano Banana). It's shown to the user directly.",
        {"prompt": _S, "aspect_ratio": {"type": "string", "enum": list(gemini_media.ASPECT_RATIOS)}}, ["prompt"],
    ),
}
# Actions with side effects outside SEMBLANCE: queued for one-tap approval
# in the UI, then run by /cowork/execute — never by the model directly.
NEEDS_APPROVAL = {"gmail_send", "calendar_create"}


async def run_approved(name: str, args: dict, account_id: str) -> dict:
    if name == "gmail_send":
        return await GmailTool().query("send_message", account_id=account_id, to=args.get("to"),
                                       subject=args.get("subject", ""), body=args.get("body", ""))
    if name == "calendar_create":
        return await CalendarTool().query("create_event", account_id=account_id, **{
            k: args[k] for k in ("summary", "start", "end", "description", "location") if args.get(k)
        })
    return {"error": f"{name} isn't an approvable action"}


class CoworkAgent(ToolLoopAgent):
    def __init__(self, account_id: str, provider: str = "auto", max_steps: int | None = None,
                 deadline_seconds: float | None = None, mcp=None):
        super().__init__(provider, max_steps or settings.COWORK_MAX_STEPS,
                         deadline_seconds or settings.AGENT_TIMEOUT_SECONDS, mcp=mcp, allow_approvals=True)
        self.tab = "cowork"
        self.account_id = account_id

    def system_prompt(self) -> str:
        return _SYSTEM.format(now=datetime.now(_SAST).strftime("%A %d %B %Y, %H:%M"))

    def tools(self) -> list[dict]:
        return list(TOOLS.values())

    async def dispatch(self, name: str, args: dict) -> dict:
        acct = self.account_id
        if name in NEEDS_APPROVAL:
            return {"ok": True, "status": "waiting for the user's approval", "summary": _approval_summary(name, args)}
        if name == "web_search":
            return await web_search(args.get("query", ""))
        if name == "fetch_url":
            return await FetchTool().fetch(args.get("url", ""))
        if name == "search_memory":
            db = await get_store()
            return {"matches": await db.search_conversations(args.get("term", ""), limit=20)}
        if name == "gmail_search":
            return await GmailTool().query("list_messages", account_id=acct, query=args.get("query", ""),
                                           max_results=args.get("max_results") or 10)
        if name == "gmail_read":
            return await GmailTool().query("read_message", account_id=acct, message_id=args.get("message_id"))
        if name == "calendar_list":
            kwargs = {"max_results": args.get("max_results") or 10}
            if args.get("time_min"):
                kwargs["time_min"] = args["time_min"]
            return await CalendarTool().query("list_events", account_id=acct, **kwargs)
        if name == "drive_list":
            return await DriveTool().query("list_files", account_id=acct)
        if name == "drive_read":
            return await DriveTool().query("read_file", account_id=acct, file_id=args.get("file_id"))
        if name == "drive_create_note":
            return await DriveTool().query("create_note", account_id=acct, title=args.get("title", "Untitled note"),
                                           content=args.get("content", ""))
        if name == "drive_append_note":
            return await DriveTool().query("append_note", account_id=acct, file_id=args.get("file_id"),
                                           content=args.get("content", ""))
        if name == "set_reminder":
            try:
                due = datetime.fromisoformat(args.get("when", "").replace("Z", "+00:00"))
            except ValueError:
                return {"ok": False, "error": "when must be an RFC3339 datetime, e.g. 2026-10-02T09:00:00+02:00"}
            if due.tzinfo is None:
                due = due.replace(tzinfo=_SAST)
            db = await get_store()
            row = await db.add_reminder(acct, args.get("message", ""), int(due.timestamp()))
            return {"ok": True, "id": row["id"], "due": due.astimezone(_SAST).strftime("%a %d %b %H:%M")}
        if name == "list_reminders":
            db = await get_store()
            return {"reminders": [
                {"id": r["id"], "message": r["message"],
                 "due": datetime.fromtimestamp(r["due_at"], _SAST).strftime("%a %d %b %H:%M")}
                for r in await db.list_reminders(acct)
            ]}
        if name == "contacts_search":
            return await ContactsTool().query("search_contacts", account_id=acct, query=args.get("query", ""))
        if name == "generate_image":
            return await gemini_media.generate_image(args.get("prompt", ""), args.get("aspect_ratio") or "1:1")
        return {"ok": False, "error": f"unknown tool {name}"}

    def extra_events(self, call_id: str, name: str, args: dict, result: dict) -> list[dict]:
        if name in NEEDS_APPROVAL:
            return [{"type": "approval", "id": call_id, "name": name, "args": args, "summary": result["summary"]}]
        if name == "generate_image" and result.get("ok"):
            return [{"type": "image", "id": call_id, "mime": result["mime"], "base64": result["base64"],
                     "prompt": args.get("prompt", "")}]
        return []

    def model_view(self, result: dict) -> dict:
        if "base64" in result:
            return {"ok": True, "result": "Image generated and shown to the user."}
        return super().model_view(result)


def _approval_summary(name: str, args: dict) -> str:
    if name == "gmail_send":
        return f"Send email to {args.get('to')}: \"{args.get('subject', '')}\""
    return f"Add calendar event \"{args.get('summary')}\" {args.get('start')} → {args.get('end')}"
