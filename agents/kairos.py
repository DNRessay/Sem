import asyncio
import time

import httpx

from config import settings

TICK_BUDGET = 15  # seconds


class KairosDaemon:
    """
    Always-on background daemon. 15s blocking budget per tick.
    Outreach (WhatsApp, Telegram, Slack, GitHub alerts) routed through OpenClaw gateway.
    3 exclusive actions: push notification, file delivery, PR subscription.
    """

    def __init__(self):
        self._running = False
        self._audit: list[dict] = []
        self._openclaw_url = settings.OPENCLAW_URL  # empty = outreach calls no-op, logged and swallowed

    async def start(self):
        """Heavy-tier: continuous loop. Only viable on an always-on process
        (EC2/Fargate) — never inside Lambda, which freezes between invocations."""
        self._running = True
        while self._running:
            await self.run_once()
            await asyncio.sleep(60)

    def stop(self):
        self._running = False

    async def run_once(self):
        """Medium-tier: a single tick. This is what the scheduled Lambda
        (tick_handler.py) calls once per EventBridge firing."""
        try:
            await asyncio.wait_for(self._tick(), timeout=TICK_BUDGET)
        except asyncio.TimeoutError:
            self._log("tick_timeout", "Tick exceeded 15s budget")
        except Exception as e:
            self._log("tick_error", str(e))

    async def _tick(self):
        ctx = await self._evaluate_context()
        if ctx.get("should_act"):
            action = ctx["action"]
            if action == "push_notification":
                await self._push_notification(ctx["message"], ctx.get("channel", "default"))
            elif action == "file_delivery":
                await self._file_delivery(ctx["file_path"], ctx.get("channel", "default"))
            elif action == "pr_subscription":
                await self._pr_subscription(ctx["repo"])
            self._log(action, ctx.get("message", ""))

    async def _evaluate_context(self) -> dict:
        # Placeholder - in production: call QueryEngine.call_llm() to decide if action is needed
        hour = time.localtime().tm_hour
        if hour == 9:
            return {"should_act": True, "action": "push_notification", "message": "Good morning — daily briefing ready."}
        return {"should_act": False}

    async def _push_notification(self, message: str, channel: str):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self._openclaw_url}/api/send",
                    json={"channel": channel, "message": message},
                    headers={"x-api-key": settings.SECRET_KEY},
                )
        except Exception as e:
            self._log("push_error", str(e))

    async def _file_delivery(self, file_path: str, channel: str):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                with open(file_path, "rb") as f:
                    await client.post(
                        f"{self._openclaw_url}/api/send-file",
                        files={"file": f},
                        data={"channel": channel},
                        headers={"x-api-key": settings.SECRET_KEY},
                    )
        except Exception as e:
            self._log("file_error", str(e))

    async def _pr_subscription(self, repo: str):
        self._log("pr_subscription", f"Subscribed to {repo}")

    def _log(self, action: str, detail: str):
        self._audit.append({"ts": time.time(), "action": action, "detail": detail})

    def get_audit(self) -> list[dict]:
        return list(self._audit)
