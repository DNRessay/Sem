from fastapi import APIRouter, Depends

from config import settings
from gateway.auth import require_account
from pipeline import llm_providers

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
