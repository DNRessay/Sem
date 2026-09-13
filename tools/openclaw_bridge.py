import httpx

from config import settings


class OpenClawBridge:
    """
    SEMBLANCE → OpenClaw gateway bridge.
    OpenClaw runs at OPENCLAW_URL (default: localhost:18789).
    Handles all channel routing: WhatsApp, Telegram, Slack, Discord, GitHub, and 20+ more.
    Clone openclaw: git submodule add https://github.com/openclaw/openclaw.git openclaw
    Run it: cd openclaw && pnpm install && pnpm openclaw setup && pnpm gateway:watch
    """

    def __init__(self):
        self.base = settings.OPENCLAW_URL  # empty = feature disabled; calls fail closed
        self.key = settings.SECRET_KEY

    def _headers(self) -> dict:
        return {"x-api-key": self.key, "Content-Type": "application/json"}

    async def send_message(self, channel: str, message: str, session_id: str = None) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self.base}/api/send",
                json={"channel": channel, "message": message, "session_id": session_id},
                headers=self._headers(),
            )
            return r.json()

    async def send_whatsapp(self, phone: str, message: str) -> dict:
        return await self.send_message("whatsapp", message, session_id=phone)

    async def send_telegram(self, chat_id: str, message: str) -> dict:
        return await self.send_message("telegram", message, session_id=chat_id)

    async def github_create_issue(self, repo: str, title: str, body: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self.base}/api/skills/github/create-issue",
                json={"repo": repo, "title": title, "body": body},
                headers=self._headers(),
            )
            return r.json()

    async def github_review_pr(self, repo: str, pr_number: int, comment: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self.base}/api/skills/github/review-pr",
                json={"repo": repo, "pr": pr_number, "comment": comment},
                headers=self._headers(),
            )
            return r.json()

    async def list_channels(self) -> list:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base}/api/channels", headers=self._headers())
            return r.json().get("channels", [])

    async def install_skill(self, skill_name: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{self.base}/api/skills/install",
                json={"skill": skill_name},
                headers=self._headers(),
            )
            return r.json()

    async def webhook_receive(self, payload: dict) -> dict:
        """Forward inbound webhook from any platform into SEMBLANCE pipeline."""
        channel = payload.get("channel", "unknown")
        message = payload.get("message", "")
        session_id = payload.get("session_id", channel)
        return {"channel": channel, "message": message, "session_id": session_id}
