import httpx

from config import settings


class WhatsAppTool:
    BASE = "https://graph.facebook.com/v18.0"

    async def send(self, phone: str, message: str) -> dict:
        if not settings.WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_ID:
            return {"error": "WHATSAPP_TOKEN or WHATSAPP_PHONE_ID not set"}
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": message},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self.BASE}/{settings.WHATSAPP_PHONE_ID}/messages",
                json=payload,
                headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"},
            )
            return r.json()