import base64
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from gateway.auth import issue_token, require_account, verify_passphrase
from pipeline.agent_intent import (
    detect_explore_intent,
    detect_plan_intent,
    explore_status_label,
    format_matches,
    format_plan,
    plan_status_label,
    run_explore_intent,
    run_plan_intent,
)
from pipeline.bootstrap import Bootstrap
from pipeline.repo_context import (
    detect_repo_intent,
    fetch_repo_file_raw,
    repo_status_label,
    run_repo_intent,
)
from pipeline.session_title import generate_title
from pipeline.web_context import detect_web_intent, run_web_intent, status_label
from storage.embeddings import embed_text
from storage.neon_store import get_store
from tau.tau_engine import TAUEngine

router = APIRouter()
_tau = TAUEngine()


def _get_trust(request: Request) -> str:
    key = request.headers.get("x-api-key", "")
    if key == settings.SECRET_KEY:
        return "BYPASS"
    return settings.TRUST_MODE


@router.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    passphrase = body.get("passphrase", "")
    if not passphrase:
        raise HTTPException(400, "passphrase required")

    db = await get_store()
    account = await db.get_account("owner")
    if not account or not verify_passphrase(passphrase, account["passphrase_hash"]):
        raise HTTPException(401, "Incorrect passphrase")

    return {"token": issue_token(account["id"], account["role"])}


def _is_image(attachment: dict) -> bool:
    return (attachment.get("mime") or "").startswith("image/")


def _extract_pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx_text(raw: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(raw))
    return "\n".join(p.text for p in document.paragraphs)


def _attachment_text(a: dict) -> str:
    """Plain-text attachments (from the frontend's client-side FileReader
    path) carry their text directly in `content`. Binary formats we can't
    read client-side (PDF, Word) instead carry base64 + a mime type, and get
    extracted here, server-side, into the same plain text."""
    if a.get("content") is not None:
        return a["content"]

    mime = a.get("mime", "")
    b64 = a.get("base64", "")
    if not b64:
        return ""
    raw = base64.b64decode(b64)

    if mime == "application/pdf":
        return _extract_pdf_text(raw)
    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return _extract_docx_text(raw)
    return ""


def _fold_attachments(user_msg: str, attachments: list) -> str:
    """Appends uploaded/fetched file content to the query as fenced blocks the
    model can read like any other context — there's no separate multimodal
    text channel on the Groq models this app runs on, so text (including
    text extracted server-side from PDF/Word attachments) is folded straight
    into the message rather than sent out-of-band. Image attachments are
    handled separately by Bootstrap, not folded here — see gateway/router.py
    `chat()`."""
    if not attachments:
        return user_msg
    blocks = ["<attachments>"]
    for a in attachments:
        name = a.get("name", "file")
        content = _attachment_text(a)
        blocks.append(f'<file name="{name}">\n{content}\n</file>')
    blocks.append("</attachments>")
    return f"{user_msg}\n\n" + "\n".join(blocks)


@router.post("/chat")
async def chat(request: Request, trust: str = Depends(_get_trust), _account: dict = Depends(require_account)):
    body = await request.json()
    raw_msg = body.get("message", "")
    session_id = body.get("session_id", "default")
    history = body.get("history", [])
    attachments = body.get("attachments", [])
    web_search_enabled = body.get("web_search_enabled", True)

    if not raw_msg:
        raise HTTPException(400, "message required")

    images = [a for a in attachments if _is_image(a)]
    text_attachments = [a for a in attachments if not _is_image(a)]

    # augmented is what the model sees (attachments + fetched/searched
    # content folded in); raw_msg is what's persisted as "what the user
    # said" and embedded into long-term memory — these used to be the same
    # string, so a search result dump ended up saved and later displayed as
    # if the user had typed it themselves.
    augmented = _fold_attachments(raw_msg, text_attachments)
    tau_ctx = await _tau.observe_and_inject(session_id, augmented, history)
    bootstrap = Bootstrap(trust_mode=trust, tau_context=tau_ctx)
    # Deliberately raw_msg, not augmented: web-intent detection must only look
    # at what the user actually typed. Scanning attachment content too means
    # any URL-shaped text sitting in an attached file — a regex literal in a
    # workflow script, an example in a README, anything — gets treated as
    # "fetch this," hijacking the user's real question and hanging on a
    # garbage host until the fetch tool's own timeout. Also off entirely
    # when the user has toggled "Web search" off in the attach menu.
    web_intent = detect_web_intent(raw_msg) if web_search_enabled else None
    # Checked first/preferred over web_intent when both could match ("search
    # the repo for X" contains "search", which alone would trigger a web
    # search) — repo phrasing is the more specific signal, and only ever
    # does anything when this session actually has an active cloned repo.
    repo_intent = detect_repo_intent(raw_msg)
    # Step 7 (sub-agent delegation) wired to a real chat message: "make a
    # plan for X" routes through CablesMan -> PlanAgent, "search the code
    # for X" through CablesMan -> ExploreAgent. Checked after repo_intent
    # (more specific, and only fires with an active attached repo) and
    # before web_intent, on raw_msg only for the same reason web/repo intent
    # detection is — see the comment above web_intent.
    plan_intent = detect_plan_intent(raw_msg)
    explore_intent = detect_explore_intent(raw_msg)

    async def _bypass_with_reply(kind: str, label: str, detail: str, reply: str):
        """Shared tail for an intent that answers the message completely on
        its own, with no LLM call needed to phrase around it (a generated
        plan, a code search's results) — same shape as the repo "read"
        bypass above, just factored out since two more intents now need it.
        Streams the tool chip + reply, persists both turns, embeds only the
        query (the reply's source of truth — the plan, the source file —
        lives outside chat history and would go stale/duplicate here), and
        generates a session title on the first turn."""
        tool = {"kind": kind, "label": label, "detail": detail}
        yield f"data: {json.dumps({'tool': tool})}\n\n"
        for i in range(0, len(reply), 400):
            yield f"data: {json.dumps({'chunk': reply[i:i + 400]})}\n\n"

        db = await get_store()
        marker = f"[[SEMBLANCE_TOOL:{json.dumps({'kind': kind, 'label': label})}]]\n"
        await db.save_turn(session_id, "user", raw_msg)
        await db.save_turn(session_id, "assistant", f"{marker}{reply}")
        query_embedding = await embed_text(raw_msg)
        await db.save_memory(session_id, raw_msg, embedding=query_embedding)

        if not history:
            title = await generate_title(raw_msg, reply)
            if title:
                await db.set_session_title(session_id, title)
                yield f"data: {json.dumps({'title': title})}\n\n"

        yield "data: [DONE]\n\n"

    async def stream_gen():
        msg = augmented
        tool_marker = ""
        if repo_intent and repo_intent[0] == "read":
            # A file read bypasses the LLM entirely — see
            # pipeline.repo_context.fetch_repo_file_raw for why: reproducing
            # exact file content through a max_tokens-limited model both
            # wastes its (rate-limited) output budget and reliably
            # truncates partway through anything more than a couple
            # thousand characters, with no reasoning involved in the task
            # anyway. Falls through to the normal flow below only if there's
            # no active repo or the read failed, so the model can still say
            # something sensible rather than the request just going silent.
            _, target = repo_intent
            yield f"data: {json.dumps({'status': repo_status_label('read', target)})}\n\n"
            raw = await fetch_repo_file_raw(target, session_id)
            if raw:
                path, content = raw
                ext = path.rsplit(".", 1)[-1] if "." in path else ""
                reply = f"Here's the full `{path}` from the repo:\n\n```{ext}\n{content}\n```"
                label = f"Reading {path}"
                tool = {"kind": "read", "label": label, "detail": f'<repo_file path="{path}">\n{content}\n</repo_file>'}
                yield f"data: {json.dumps({'tool': tool})}\n\n"
                for i in range(0, len(reply), 400):
                    yield f"data: {json.dumps({'chunk': reply[i:i + 400]})}\n\n"

                db = await get_store()
                marker = f"[[SEMBLANCE_TOOL:{json.dumps({'kind': 'read', 'label': label})}]]\n"
                await db.save_turn(session_id, "user", raw_msg)
                await db.save_turn(session_id, "assistant", f"{marker}{reply}")
                # Only the query gets embedded, not the reply — the file's
                # real content already lives in the repo clone and would
                # just go stale/duplicate there the next time it's asked
                # about (same reasoning as pipeline.bootstrap.Bootstrap.run's
                # tool-driven-reply skip).
                query_embedding = await embed_text(raw_msg)
                await db.save_memory(session_id, raw_msg, embedding=query_embedding)

                if not history:
                    title = await generate_title(raw_msg, reply)
                    if title:
                        await db.set_session_title(session_id, title)
                        yield f"data: {json.dumps({'title': title})}\n\n"

                yield "data: [DONE]\n\n"
                return

        if repo_intent and repo_intent[0] == "grep":
            kind, target = repo_intent
            yield f"data: {json.dumps({'status': repo_status_label(kind, target)})}\n\n"
            repo_block = await run_repo_intent(target, session_id)
            if repo_block:
                msg = (
                    f"{msg}\n\n"
                    "<system_note>The repo data below was already retrieved for "
                    "this message before you saw it. Do not say you are reading, "
                    "searching, or pulling it — just answer directly using it "
                    "now. If it doesn't actually answer the question, say so "
                    "instead of guessing.</system_note>\n"
                    f"{repo_block}"
                )
                tool = {"kind": kind, "label": repo_status_label(kind, target).rstrip("…"), "detail": repo_block}
                yield f"data: {json.dumps({'tool': tool})}\n\n"
                tool_marker = f"[[SEMBLANCE_TOOL:{json.dumps({'kind': kind, 'label': tool['label']})}]]\n"
        elif plan_intent:
            yield f"data: {json.dumps({'status': plan_status_label()})}\n\n"
            plan = await run_plan_intent(plan_intent, session_id)
            reply = format_plan(plan)
            if reply:
                async for line in _bypass_with_reply("plan", "Planning", json.dumps(plan), reply):
                    yield line
                return
            # No plan came back (PlanAgent/QueryEngine failure) — fall
            # through to the normal Bootstrap flow below rather than
            # leaving the request hanging with no reply at all.
        elif explore_intent:
            yield f"data: {json.dumps({'status': explore_status_label(explore_intent)})}\n\n"
            matches = await run_explore_intent(explore_intent, session_id)
            reply = format_matches(explore_intent, matches)
            if reply:
                label = f'Searching code for "{explore_intent}"'
                async for line in _bypass_with_reply("explore", label, reply, reply):
                    yield line
                return
        elif web_intent:
            kind, target = web_intent
            yield f"data: {json.dumps({'status': status_label(kind, target)})}\n\n"
            web_block = await run_web_intent(kind, target, session_id=session_id)
            if web_block:
                # Explicit framing, not just the raw block: the models this
                # app runs have no real tool-calling wired up, but SEMBLANCE.md
                # tells them to "prefer web search" — without this note a model
                # reads that instruction, sees data already sitting in context,
                # and narrates a fake in-progress fetch ("let me grab that for
                # you") instead of just answering from what's already here.
                msg = (
                    f"{msg}\n\n"
                    "<system_note>The web data below was already retrieved for "
                    "this message before you saw it. Do not say you are fetching, "
                    "grabbing, or searching for it — just answer directly using "
                    "it now. If it's generic/unrelated and doesn't actually answer "
                    "the question, say the search didn't find it — never invent "
                    "specific facts to fill the gap, even if the user insists this "
                    "is the right result. Every specific claim (credentials, "
                    "employer, affiliations, counts, etc) must be literally present "
                    "in the data below, not assembled from what typically fits the "
                    "description.</system_note>\n"
                    f"{web_block}"
                )
                tool = {"kind": kind, "label": status_label(kind, target).rstrip("…"), "detail": web_block}
                yield f"data: {json.dumps({'tool': tool})}\n\n"
                tool_marker = f"[[SEMBLANCE_TOOL:{json.dumps({'kind': kind, 'label': tool['label']})}]]\n"

        reply_parts = []
        async for chunk in bootstrap.run(
            msg, session_id, history, images=images,
            display_query=raw_msg, assistant_prefix=tool_marker,
        ):
            reply_parts.append(chunk)
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"

        if not history:
            # First turn of a new session — generate a real short title
            # instead of leaving the sidebar/header showing the raw first
            # message or a bare session ID. Once per session, not every
            # turn: this account's Groq rate limit is tight enough that an
            # extra call on every message would add up fast.
            title = await generate_title(raw_msg, "".join(reply_parts))
            if title:
                db = await get_store()
                await db.set_session_title(session_id, title)
                yield f"data: {json.dumps({'title': title})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


@router.get("/status/{session_id}")
async def status(session_id: str, _account: dict = Depends(require_account)):
    """Backs AgentFeed.jsx's 3s poll — the most recent CABLES MAN activity
    for this session (a route decision from core.cables_man.CablesMan.route,
    or a tool call from pipeline.tool_execution.ToolExecution), read back
    from the agent_events table since a chat POST and this GET are almost
    always different Lambda invocations with no shared memory."""
    db = await get_store()
    event = await db.get_latest_agent_event(session_id)
    return {"session_id": session_id, "status": "active", "event": event}


@router.get("/sessions")
async def sessions(_account: dict = Depends(require_account)):
    db = await get_store()
    return {"sessions": await db.list_sessions()}


@router.get("/history/{session_id}")
async def history(session_id: str, _account: dict = Depends(require_account)):
    db = await get_store()
    return {
        "session_id": session_id,
        "title": await db.get_session_title(session_id),
        "turns": await db.get_conversation(session_id),
    }


@router.get("/health")
async def health():
    return {"status": "ok", "version": "semblance-v9"}
