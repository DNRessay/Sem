import re
from collections import deque
from dataclasses import dataclass

import httpx

from config import settings


@dataclass
class EMU:
    label: str
    confidence: float
    valence: float   # -1 (negative) to +1 (positive)
    arousal: float   # 0 (calm) to 1 (excited)


EMOTION_LEXICON = {
    "joy":       (["happy", "great", "excited", "love", "awesome", "fantastic", "thrilled"],       0.9,  0.8),
    "anger":     (["angry", "frustrated", "annoyed", "furious", "mad", "hate"],                   -0.8,  0.9),
    "sadness":   (["sad", "depressed", "unhappy", "upset", "disappointed", "grief"],              -0.7,  0.2),
    "fear":      (["scared", "worried", "anxious", "nervous", "afraid", "terrified"],             -0.6,  0.8),
    "surprise":  (["wow", "unexpected", "shocking", "incredible", "unbelievable"],                 0.3,  0.9),
    "disgust":   (["disgusting", "gross", "horrible", "awful", "terrible"],                       -0.8,  0.6),
    "trust":     (["reliable", "trust", "confident", "sure", "certain", "believe"],                0.7,  0.3),
    "neutral":   ([],                                                                               0.0,  0.0),
}


# (valence, arousal) for the classifier's labels — the same scale as the lexicon.
_AFFECT = {"joy": (0.9, 0.8), "anger": (-0.8, 0.9), "sadness": (-0.7, 0.2), "fear": (-0.6, 0.8),
           "surprise": (0.3, 0.9), "disgust": (-0.8, 0.6), "neutral": (0.0, 0.0)}

TONE_GUIDANCE = {
    "anger": "The user sounds frustrated: acknowledge it briefly, skip pleasantries, get straight to a fix.",
    "fear": "The user sounds worried or stressed: be calm and reassuring, give clear next steps.",
    "sadness": "The user sounds down: be warm and supportive without overdoing it.",
    "disgust": "The user is unhappy with something: acknowledge it and focus on what can be done.",
    "joy": "The user is in a good mood: match the energy, keep it light.",
    "surprise": "The user is surprised: explain clearly what happened.",
}


def emotion_url() -> str:
    if settings.MODAL_EMOTION_URL:
        return settings.MODAL_EMOTION_URL
    url = settings.MODAL_EMBEDDINGS_URL
    # Modal names class endpoints <app>-<class>-<method>: the emotion method sits beside "embed".
    return re.sub(r"-embed(\.modal\.run)", r"-emotion\1", url) if re.search(r"-embed\.modal\.run", url) else ""


class NatureSCIEngine:
    """
    Reads the emotion in a message. Uses the open-source DistilRoBERTa
    emotion classifier on Modal (modal_app/embeddings.py) when deployed,
    and a small word list otherwise. Its result steers Sem's tone each turn
    (tau/tau_engine.py) and weights memory salience.
    """

    def __init__(self):
        # Recent readings only (this object lives as long as a warm Lambda instance, so a plain list grew forever).
        self._history: deque[EMU] = deque(maxlen=20)

    def analyse_text(self, text: str) -> EMU:
        emu = self._lexicon_classify(text.lower())
        self._history.append(emu)
        return emu

    async def classify(self, text: str) -> EMU:
        """The model's reading when available, the word list otherwise."""
        url = emotion_url()
        if url and text.strip():
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    r = await client.post(url, json={"text": text})
                body = r.json() if r.status_code == 200 else {}
                scores = {k: float(v) for k, v in (body.get("scores") or {}).items()} if isinstance(body, dict) else {}
                if scores:
                    label, confidence = max(scores.items(), key=lambda kv: kv[1])
                    valence, arousal = _AFFECT.get(label, (0.0, 0.0))
                    emu = EMU(label, float(confidence), valence, arousal)
                    self._history.append(emu)
                    return emu
            except Exception:  # any bad answer from the model falls back to the word list, never fails the turn
                pass
        return self.analyse_text(text)

    @staticmethod
    def guidance(emu: EMU) -> str:
        """A one-line tone instruction for confident, non-neutral readings."""
        if emu.label == "neutral" or emu.confidence < 0.5:
            return ""
        return TONE_GUIDANCE.get(emu.label, "")

    def track_sequence(self, history: list[dict]) -> dict:
        """RNN-style: track emotional arc across turns."""
        emus = [self.analyse_text(m.get("content", "")) for m in history if m.get("role") == "user"]
        if not emus:
            return {"dominant": "neutral", "valence_trend": 0.0, "arousal_avg": 0.0}
        valences = [e.valence for e in emus]
        trend = (valences[-1] - valences[0]) if len(valences) > 1 else 0.0
        dominant = max(set(e.label for e in emus), key=lambda label: sum(1 for e in emus if e.label == label))
        return {
            "dominant": dominant,
            "valence_trend": round(trend, 3),
            "arousal_avg": round(sum(e.arousal for e in emus) / len(emus), 3),
        }

    def get_emu_weights(self) -> dict:
        if not self._history:
            return {}
        recent = list(self._history)[-5:]
        weights = {}
        for emu in recent:
            weights[emu.label] = weights.get(emu.label, 0) + emu.confidence
        total = sum(weights.values()) or 1
        return {k: round(v / total, 3) for k, v in weights.items()}

    def modulate_prompt(self, base_prompt: str, emu: EMU) -> str:
        if emu.valence < -0.5:
            return f"[tone: empathetic and supportive]\n{base_prompt}"
        if emu.arousal > 0.7:
            return f"[tone: calm and measured]\n{base_prompt}"
        return base_prompt

    def _lexicon_classify(self, text: str) -> EMU:
        scores = {}
        for emotion, (keywords, valence, arousal) in EMOTION_LEXICON.items():
            if emotion == "neutral":
                continue
            count = sum(1 for kw in keywords if re.search(rf"\b{kw}\b", text))
            if count:
                scores[emotion] = (count, valence, arousal)

        if not scores:
            return EMU("neutral", 1.0, 0.0, 0.0)

        top = max(scores.items(), key=lambda x: x[1][0])
        label, (count, valence, arousal) = top
        confidence = min(1.0, count * 0.3)
        return EMU(label, confidence, valence, arousal)
