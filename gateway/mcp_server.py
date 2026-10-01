"""SEMBLANCE as an MCP server (Streamable HTTP, stateless JSON replies), so
Claude Code, Claude Desktop, Cursor or any MCP client can use it:

    claude mcp add --transport http semblance <API_URL>/mcp --header "Authorization: Bearer <MCP key>"

The MCP key comes from Settings in the app (POST /mcp/key)."""
import json

from agents.code_agent import CodeAgent
from agents.cowork_agent import CoworkAgent
from agents.research_agent import ResearchAgent
from pipeline import llm_providers
from pipeline.ad_studio import PLACEMENTS, write_variants
from pipeline.code_tasks import connector_token, open_pr, valid_target
from pipeline.mcp_tools import MCPToolset
from pipeline.site_brief import learn_site
from storage.neon_store import get_store
from tools import gemini_media
from tools.code_workspace import CodeWorkspace
from tools.web.search import web_search

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "semblance", "title": "SEMBLANCE", "version": "1.0"}
_INSTRUCTIONS = ("SEMBLANCE is a personal AI assistant. Use `ask` for quick questions, `research` for cited web "
                 "research, `cowork` for multi-step tasks over email/calendar/Drive/web, `code` to change a GitHub or "
                 "GitLab repo (then `code_open_pr`), and the design tools for marketing images and ad copy.")

_S = {"type": "string"}
_MODEL = {"type": "string", "description": "Model picker id: auto (free), gemini, groq, anthropic, openai, qwen, "
                                           "deepseek, kimi, or hf:owner/model. Default auto."}


def _tool(name, title, description, props, required, read_only=False):
    return {"name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": props, "required": required},
            "annotations": {"readOnlyHint": read_only}}


TOOLS = [
    _tool("ask", "Ask SEMBLANCE", "Quick answer from SEMBLANCE.", {"message": _S, "model": _MODEL}, ["message"], True),
    _tool("research", "Deep research", "Searches the web, reads several sources, answers with citations.",
          {"question": _S, "model": _MODEL}, ["question"], True),
    _tool("cowork", "Co-work task", "Runs a multi-step task with web, Gmail, Calendar, Drive notes and images. "
          "Sending email or adding events is never done here — those wait for approval in the SEMBLANCE app.",
          {"task": _S, "model": _MODEL}, ["task"]),
    _tool("code", "Code task", "Clones/updates a repo in SEMBLANCE's workspace and works on it (read, edit, run tests). "
          "Nothing is pushed — call code_open_pr afterwards. mode=plan only explores and returns a plan.",
          {"provider": {"type": "string", "enum": ["github", "gitlab"]}, "repo": {"type": "string", "description": "owner/name"},
           "task": _S, "mode": {"type": "string", "enum": ["act", "plan"]}, "model": _MODEL},
          ["provider", "repo", "task"]),
    _tool("code_open_pr", "Open pull request", "Opens a PR/MR with the workspace's changes from the last code task.",
          {"provider": {"type": "string", "enum": ["github", "gitlab"]}, "repo": _S, "title": _S, "body": _S},
          ["provider", "repo", "title"]),
    _tool("web_search", "Web search", "Search the web.", {"query": _S}, ["query"], True),
    _tool("search_memory", "Search past chats", "Search the owner's past SEMBLANCE conversations.", {"term": _S}, ["term"], True),
    _tool("generate_image", "Generate image", "Create an image (Gemini Nano Banana).",
          {"prompt": _S, "aspect_ratio": {"type": "string", "enum": list(gemini_media.ASPECT_RATIOS)}}, ["prompt"]),
    _tool("speak", "Text to speech", "Read text aloud (Gemini voice). Returns WAV audio.",
          {"text": _S, "voice": {"type": "string", "enum": list(gemini_media.VOICES)}}, ["text"]),
    _tool("learn_website", "Learn a business from its website", "Reads a business website and writes a marketing brief.",
          {"url": _S, "model": _MODEL}, ["url"], True),
    _tool("write_ads", "Write ads", "Writes ad copy and image prompts per placement for a business brief + campaign.",
          {"brief": _S, "campaign": _S, "placements": {"type": "array", "items": {"type": "string", "enum": list(PLACEMENTS)}},
           "count": {"type": "integer"}, "model": _MODEL}, ["brief", "campaign"], True),
]


def _text(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def _drain(agent, task: str) -> dict:
    agent.allow_handoff = False  # an outside MCP client has no Sem tabs to switch to
    texts, steps, pending, images, error = [], 0, [], [], None
    async for ev in agent.run(task):
        if ev["type"] == "text":
            texts.append(ev["text"])
        elif ev["type"] == "tool":
            steps += 1
        elif ev["type"] == "approval":
            pending.append(ev["summary"])
        elif ev["type"] == "image":
            images.append(ev)
        elif ev["type"] == "error":
            error = ev["text"]
    answer = texts[-1] if texts else (error or "No answer came back.")
    if pending:
        answer += "\n\nWaiting for approval in the SEMBLANCE app (not run):\n" + "\n".join(f"- {p}" for p in pending)
    content = [{"type": "text", "text": answer}]
    content += [{"type": "image", "data": i["base64"], "mimeType": i["mime"]} for i in images]
    return {"content": content, "isError": bool(error and not texts)}


async def call_tool(name: str, args: dict, account_id: str) -> dict:
    model = args.get("model") or "auto"
    if name == "ask":
        result = await llm_providers.complete(model, [
            {"role": "system", "content": "You are SEMBLANCE, a direct, helpful personal assistant. Never claim to be "
                                          "Claude, GPT or any other vendor's model."},
            {"role": "user", "content": args.get("message", "")},
        ])
        return _text(result["error"], True) if "error" in result else _text(result.get("content") or "")
    if name == "research":
        return await _drain(ResearchAgent(provider=model), args.get("question", ""))
    if name == "cowork":
        mcp = await MCPToolset.for_account(account_id)
        return await _drain(CoworkAgent(account_id, provider=model, mcp=mcp), args.get("task", ""))
    if name in ("code", "code_open_pr"):
        provider, repo = args.get("provider", "github"), (args.get("repo") or "").strip()
        if not valid_target(provider, repo):
            return _text("provider must be github/gitlab and repo like owner/name", True)
        ws, token = CodeWorkspace(provider, repo), await connector_token(account_id, provider)
        if name == "code_open_pr":
            if not token:
                return _text(f"Connect {provider} in the SEMBLANCE app first.", True)
            pr = await open_pr(ws, token, args.get("title", ""), args.get("body", ""))
            return _text(f"Opened {pr['url']}" if pr.get("ok") else pr.get("error", "PR failed"), not pr.get("ok"))
        opened = await ws.open(token)
        if not opened.get("ok"):
            return _text(f"Couldn't open {repo}: {opened.get('error')}", True)
        mcp = await MCPToolset.for_account(account_id)
        result = await _drain(CodeAgent(ws, mode=args.get("mode") or "act", provider=model, mcp=mcp), args.get("task", ""))
        changes = await ws.changes()
        if changes.get("files"):
            result["content"][0]["text"] += "\n\nChanged files: " + ", ".join(sorted(changes["files"]))
        return result
    if name == "web_search":
        r = await web_search(args.get("query", ""))
        return _text(json.dumps(r.get("results"), indent=1) if r.get("ok") else r.get("error", ""), not r.get("ok"))
    if name == "search_memory":
        db = await get_store()
        return _text(json.dumps(await db.search_conversations(args.get("term", ""), limit=20), default=str))
    if name == "generate_image":
        r = await gemini_media.generate_image(args.get("prompt", ""), args.get("aspect_ratio") or "1:1")
        if not r["ok"]:
            return _text(r["error"], True)
        return {"content": [{"type": "image", "data": r["base64"], "mimeType": r["mime"]}], "isError": False}
    if name == "speak":
        r = await gemini_media.speak(args.get("text", ""), args.get("voice") or "Kore")
        if not r["ok"]:
            return _text(r["error"], True)
        return {"content": [{"type": "audio", "data": r["base64"], "mimeType": r["mime"]}], "isError": False}
    if name == "learn_website":
        r = await learn_site(args.get("url", ""), model)
        return _text(r["brief"] if r["ok"] else r["error"], not r["ok"])
    if name == "write_ads":
        r = await write_variants(args.get("brief", ""), args.get("campaign", ""), args.get("placements") or [],
                                 args.get("count") or 2, model)
        return _text(json.dumps(r["variants"], indent=1) if r["ok"] else r["error"], not r["ok"])
    return _text(f"Unknown tool {name}", True)


async def handle(message: dict, account_id: str) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in message:
        return None
    mid, method, params = message["id"], message.get("method"), message.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        result = {"protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                  "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                  "instructions": _INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        if name not in {t["name"] for t in TOOLS}:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            result = await call_tool(name, params.get("arguments") or {}, account_id)
        except Exception as e:  # a tool failure is a result the client can show, not a protocol error
            result = _text(f"{name} failed: {str(e)[:300]}", True)
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}
