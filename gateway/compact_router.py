from fastapi import APIRouter, Depends, HTTPException, Request

from gateway.auth import require_account
from pipeline import llm_providers

router = APIRouter()

_PROMPT = """Summarise the conversation below so it can replace it in the chat's memory. Keep everything needed to
carry on: the user's goals and preferences, decisions made, facts and numbers, file names, repo/branch names, what was
already done and what is still open. Plain bullet points, no preamble. At most about 400 words.

{transcript}"""


@router.post("/compact")
async def compact(request: Request, _account: dict = Depends(require_account)):
    """Squashes older messages into one summary (the context ring's "Compact", also run automatically near the limit)."""
    body = await request.json()
    messages = [m for m in body.get("messages") or [] if isinstance(m, dict) and m.get("content")]
    if not messages:
        raise HTTPException(400, "nothing to compact")
    transcript = "\n\n".join(f"{'User' if m.get('role') == 'user' else 'Assistant'}: {str(m['content'])[:4000]}"
                               for m in messages)[-60000:]
    result = await llm_providers.complete(body.get("model") or "auto",
                                          [{"role": "user", "content": _PROMPT.format(transcript=transcript)}],
                                          max_tokens=1200)
    if "error" in result:
        raise HTTPException(502, result["error"][:300])
    return {"summary": (result.get("content") or "").strip()}
