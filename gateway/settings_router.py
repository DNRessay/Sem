import time

from fastapi import APIRouter, Depends, HTTPException, Request

from cache.tau_cache import TAUCache
from config import settings
from gateway.auth import require_account
from pipeline import llm_providers
from storage.neon_store import get_store
from tools.video_tool import video_call

router = APIRouter(prefix="/settings")


def _feature(group: str, name: str, on: bool, enable: str, note: str = "") -> dict:
    return {"group": group, "name": name, "on": on, "enable": enable, "note": note}


@router.get("/status")
async def status(_account: dict = Depends(require_account)):
    """What's switched on, and the GitHub secret (or Modal deploy) that turns
    each thing on. Never returns a secret's value — only whether it's set."""
    s = settings
    features = [
        _feature("Models", "Groq (free)", bool(s.GROQ_API_KEY), "GROQ_API_KEY"),
        _feature("Models", "Bonsai 27B, self-hosted (free)", bool(s.LOCAL_LLM_URL),
                 "LOCAL_LLM_URL + LOCAL_LLM_API_KEY", "modal deploy modal_app/llm.py"),
        _feature("Models", "Gemini (free tier)", bool(s.GEMINI_API_KEY), "GEMINI_API_KEY"),
        _feature("Models", "Claude (paid)", bool(s.ANTHROPIC_API_KEY), "ANTHROPIC_API_KEY", s.ANTHROPIC_MODEL),
        _feature("Models", "GPT (paid)", bool(s.OPENAI_API_KEY), "OPENAI_API_KEY", s.OPENAI_MODEL),
        _feature("Models", "Qwen (paid)", bool(s.QWEN_API_KEY), "QWEN_API_KEY", s.QWEN_MODEL),
        _feature("Models", "DeepSeek (paid)", bool(s.DEEPSEEK_API_KEY), "DEEPSEEK_API_KEY", s.DEEPSEEK_MODEL),
        _feature("Models", "Kimi (paid)", bool(s.KIMI_API_KEY), "KIMI_API_KEY", s.KIMI_MODEL),
        _feature("Models", "Hugging Face (any model)", bool(s.HF_TOKEN), "HF_TOKEN"),
        _feature("Models", "Cohere overflow (free trial)", bool(s.COHERE_API_KEY), "COHERE_API_KEY"),
        _feature("Search", "SearXNG", bool(s.SEARXNG_URL), "SEARXNG_URL", "modal deploy modal_app/searxng.py"),
        _feature("Search", "SerpAPI (100/month free)", bool(s.SERP_API_KEY), "SERP_API_KEY"),
        _feature("Search", "Keyless web search (ddgs)", True, "", "always on as the last fallback"),
        _feature("Media", "Images + voice (Gemini)", bool(s.GEMINI_API_KEY), "GEMINI_API_KEY"),
        _feature("Media", "Video ads (Wan 2.1)", bool(s.MODAL_VIDEO_URL), "MODAL_VIDEO_URL + MODAL_VIDEO_SECRET",
                 "modal deploy modal_app/video.py"),
        _feature("Workspace", "Memory embeddings", bool(s.MODAL_EMBEDDINGS_URL), "MODAL_EMBEDDINGS_URL",
                 "modal deploy modal_app/embeddings.py"),
        _feature("Workspace", "Code tab workspace", bool(s.MODAL_REPO_URL), "MODAL_REPO_URL + MODAL_REPO_SECRET",
                 "modal deploy modal_app/repo_tool.py"),
        _feature("Connectors", "Google sign-in (Gmail, Calendar, Drive)", bool(s.GOOGLE_CLIENT_ID),
                 "GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET"),
        _feature("Connectors", "GitHub sign-in", bool(s.GITHUB_CLIENT_ID), "GH_OAUTH_CLIENT_ID + GH_OAUTH_CLIENT_SECRET",
                 "or paste a token in Connectors"),
        _feature("Connectors", "GitLab sign-in", bool(s.GITLAB_CLIENT_ID),
                 "GITLAB_OAUTH_CLIENT_ID + GITLAB_OAUTH_CLIENT_SECRET", "or paste a token in Connectors"),
        _feature("Background", "Reminders + morning brief", True, "",
                 f"brief at {s.KAIROS_BRIEF_HOUR:02d}:00 SAST" if s.KAIROS_MORNING_BRIEF else "brief switched off"),
        _feature("Background", "WhatsApp delivery", bool(s.OWNER_WHATSAPP_NUMBER and s.WHATSAPP_TOKEN),
                 "OWNER_WHATSAPP_NUMBER + WHATSAPP_TOKEN + WHATSAPP_PHONE_ID"),
        _feature("Background", "OpenClaw bridge", bool(s.OPENCLAW_URL), "OPENCLAW_URL"),
    ]
    limits = {
        "code_max_steps": s.CODE_MAX_STEPS, "cowork_max_steps": s.COWORK_MAX_STEPS,
        "research_max_steps": s.RESEARCH_MAX_STEPS, "agent_timeout_seconds": s.AGENT_TIMEOUT_SECONDS,
        "automation_timeout_seconds": s.AUTOMATION_TIMEOUT_SECONDS,
    }
    return {"features": features, "models": llm_providers.available(), "limits": limits,
            "mcp_url": (s.PUBLIC_API_URL or "").rstrip("/") + "/mcp" if s.PUBLIC_API_URL else ""}


# ── Account: the owner profile every chat and agent reads (TAU) ──────────────

PROFILE_FIELDS = {"name": 80, "call_me": 80, "work": 120, "location": 120, "about": 2000,
                  "preferences": 4000, "coding_preferences": 2000}


@router.get("/profile")
async def get_profile(_account: dict = Depends(require_account)):
    db = await get_store()
    model = await db.get_user_model("owner") or {}
    return {k: model.get(k, "") if isinstance(model.get(k, ""), str) else str(model.get(k)) for k in PROFILE_FIELDS}


@router.put("/profile")
async def save_profile(request: Request, _account: dict = Depends(require_account)):
    body = await request.json()
    db = await get_store()
    model = await db.get_user_model("owner") or {}
    for key, limit in PROFILE_FIELDS.items():
        if key in body:
            model[key] = str(body[key] or "").strip()[:limit]
    await db.save_user_model("owner", model)
    TAUCache().bump_version()  # every chat picks up the new profile on its next message
    return {k: model.get(k, "") for k in PROFILE_FIELDS}


# ── Memory ───────────────────────────────────────────────────────────────────

@router.get("/memory")
async def memories(q: str = "", _account: dict = Depends(require_account)):
    db = await get_store()
    return {"memories": await db.search_memories(q, limit=60), "total": await db.count_memories()}


@router.delete("/memory/{memory_id}")
async def forget(memory_id: int, _account: dict = Depends(require_account)):
    db = await get_store()
    if not await db.delete_memory(memory_id):
        raise HTTPException(404, "memory not found")
    return {"ok": True}


# ── Reminders ────────────────────────────────────────────────────────────────

@router.get("/reminders")
async def reminders(account: dict = Depends(require_account)):
    db = await get_store()
    return {"reminders": await db.list_reminders(account["account_id"])}


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: int, account: dict = Depends(require_account)):
    db = await get_store()
    if not await db.delete_reminder(account["account_id"], reminder_id):
        raise HTTPException(404, "reminder not found")
    return {"ok": True}


# ── Usage ────────────────────────────────────────────────────────────────────

@router.get("/usage")
async def usage(account: dict = Depends(require_account)):
    db = await get_store()
    now = int(time.time())
    video = await video_call("budget") if settings.MODAL_VIDEO_URL else {}
    return {
        "chats_7d": await db.count_sessions_since(now - 7 * 86400),
        "chats_30d": await db.count_sessions_since(now - 30 * 86400),
        "memories": await db.count_memories(),
        "reminders": len(await db.list_reminders(account["account_id"])),
        "automations": len(await db.list_code_automations(account["account_id"])),
        "mcp_servers": len(await db.list_mcp_servers(account["account_id"])),
        "video": {k: video.get(k) for k in ("used_usd", "cap_usd")} if video.get("ok") else None,
    }


@router.get("/aws-cost")
async def aws_cost(account: dict = Depends(require_account)):
    from tools.aws_cost import month_to_date
    return await month_to_date(account["account_id"])
