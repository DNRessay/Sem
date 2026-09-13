import re
from dataclasses import dataclass


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


class NatureSCIEngine:
    """
    Emotional intelligence ensemble.
    v1: rule-based BERT-style text classification + RNN sequential tracking.
    Upgrade path: swap _bert_classify for a real transformers BERT model.
    """

    def __init__(self):
        self._history: list[EMU] = []

    def analyse_text(self, text: str) -> EMU:
        emu = self._bert_classify(text.lower())
        self._history.append(emu)
        return emu

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
        recent = self._history[-5:]
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

    def _bert_classify(self, text: str) -> EMU:
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
