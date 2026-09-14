import base64
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from config import settings
from gateway.auth import issue_token, require_account, verify_passphrase
from pipeline.bootstrap import Bootstrap
from pipeline.web_context import detect_web_intent, run_web_intent, status_label
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
    # garbage host until the fetch tool's own timeout.
    web_intent = detect_web_intent(raw_msg)

    async def stream_gen():
        msg = augmented
        tool_marker = ""
        if web_intent:
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

        async for chunk in bootstrap.run(
            msg, session_id, history, images=images,
            display_query=raw_msg, assistant_prefix=tool_marker,
        ):
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


@router.get("/status/{session_id}")
async def status(session_id: str, _account: dict = Depends(require_account)):
    return {"session_id": session_id, "status": "active"}


@router.get("/sessions")
async def sessions(_account: dict = Depends(require_account)):
    db = await get_store()
    return {"sessions": await db.list_sessions()}


@router.get("/history/{session_id}")
async def history(session_id: str, _account: dict = Depends(require_account)):
    db = await get_store()
    return {"session_id": session_id, "turns": await db.get_conversation(session_id)}


@router.get("/health")
async def health():
    return {"status": "ok", "version": "semblance-v9"}
