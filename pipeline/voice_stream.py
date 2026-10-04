"""Voice mode, server side: TTS (Kokoro on Modal, Gemini as fallback) starts on each sentence of the reply while the rest is still being
written, and the audio comes back in the same stream as {"speech": {seq, text, url|base64}} events — no
extra request from the phone per sentence. Pieces are spoken one at a time (Gemini's TTS limit is tight);
after a rate limit the rest arrive as text only and the phone reads them with its own voice."""
import asyncio
import json
import re

from tools import media_store, tts

MAX_SPOKEN = 1200
FIRST_MIN = 20   # start talking at the first sentence this long…
NEXT_MIN = 220   # …then speak in bigger pieces (fewer TTS calls, fewer seams)


def plain_for_speech(text: str) -> str:
    text = re.sub(r"\[\[SEMBLANCE_TOOL:[^\]]*\]\]\n?", "", text or "")
    text = re.sub(r"```[\s\S]*?```", " I've put the code in the chat. ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\s+", " ", re.sub(r"[#*_`>|]", "", text)).strip()


def speakable_cut(text: str, minimum: int) -> int:
    """Where the next piece of a still-growing reply can end: after a sentence, never inside a code block."""
    if text.count("```") % 2:
        text = text[:text.rfind("```")]
    cut = 0
    for m in re.finditer(r"[.!?](?=\s)|\n", text):
        cut = m.start() + 1
        if cut >= minimum:
            break
    return cut if cut >= minimum else 0


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


async def _audio(piece: str, voice: str) -> dict:
    result = await tts.speak(piece, voice)
    if not result["ok"]:
        return {"rate_limited": bool(result.get("rate_limited"))}
    url = await media_store.save_speech(result["base64"])
    return {"url": url} if url else {"mime": result["mime"], "base64": result["base64"]}


async def with_speech(lines, voice: str = "Kore"):
    out: asyncio.Queue = asyncio.Queue()
    state = {"text": "", "consumed": 0, "spoken": 0, "seq": 0, "down": False, "last": None}

    async def speak(prev, seq: int, piece: str):
        if prev:
            await prev
        audio = {} if state["down"] else await _audio(piece, voice)
        if audio.pop("rate_limited", False):
            state["down"] = True
        await out.put(_sse({"speech": {"seq": seq, "text": piece, **audio}}))

    def queue(final: bool):
        fresh = state["text"][state["consumed"]:]
        cut = len(fresh) if final else speakable_cut(fresh, NEXT_MIN if state["consumed"] else FIRST_MIN)
        if not cut:
            return
        state["consumed"] += cut
        piece = plain_for_speech(fresh[:cut])
        if not piece or state["spoken"] >= MAX_SPOKEN:
            return
        if state["spoken"] + len(piece) > MAX_SPOKEN:
            piece = re.sub(r"[^.!?]*$", "", piece[:MAX_SPOKEN - state["spoken"]]) + " The rest is in the chat."
        state["spoken"] += len(piece)
        state["seq"] += 1
        state["last"] = asyncio.create_task(speak(state["last"], state["seq"], piece))

    async def pump():
        try:
            async for line in lines:
                if line.startswith("data: [DONE]"):
                    break
                if line.startswith('data: {"chunk"'):
                    try:
                        state["text"] += json.loads(line[6:])["chunk"]
                    except (ValueError, KeyError):
                        pass
                    queue(False)
                await out.put(line)
            queue(True)
            if state["last"]:
                await state["last"]
            await out.put(_sse({"speech_done": state["seq"]}))
            await out.put("data: [DONE]\n\n")
        finally:
            await out.put(None)

    task = asyncio.create_task(pump())
    try:
        while (line := await out.get()) is not None:
            yield line
    finally:
        if not task.done():
            task.cancel()
