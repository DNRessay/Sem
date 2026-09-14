---
name: WhatsApp Business Bot Help
description: Guidance for building/debugging WhatsApp Cloud API bots — webhook shape, message types, rate limits.
triggers: whatsapp, cloud api, webhook, business api, meta developer
---

When helping with a WhatsApp Business Cloud API bot (Python + Meta's
Graph API, the `daveebbelaar/python-whatsapp-bot` pattern):

- Inbound messages arrive as a webhook POST with a deeply nested payload —
  the actual message is at
  `entry[0].changes[0].value.messages[0]`, and the sender's number at
  `entry[0].changes[0].value.contacts[0].wa_id`. A malformed or
  non-message webhook (delivery receipts, status updates) hits this same
  endpoint — always check the shape exists before indexing into it rather
  than assuming every POST is a real inbound message.
- Sending a reply is a separate authenticated POST to
  `https://graph.facebook.com/v{version}/{phone_number_id}/messages` with
  a permanent access token, not a response to the webhook request itself.
- Webhook verification (the initial GET handshake) checks a
  `hub.verify_token` you chose against `hub.challenge`, and must echo the
  challenge back as plain text on a match.
- Free-form text replies only work within a 24-hour customer service
  window after the user's last message; outside that window, only
  pre-approved template messages can be sent.
- Rotate/pool API keys for any LLM backing the bot (Groq, etc.) — a
  WhatsApp bot's traffic pattern is bursty and can hit per-minute rate
  limits faster than a typical chat UI would.
