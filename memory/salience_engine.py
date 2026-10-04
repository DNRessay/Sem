import time


def _unit(x: float) -> float:
    return max(0.0, min(1.0, float(x or 0)))


class SalienceEngine:
    def score(self, memory: dict, emu_weights: dict, surprise_delta: float) -> float:
        """0..1: newer (fades over 30 days), more emotional and more unusual memories score higher."""
        created = memory.get("created_at") or time.time()  # a stored None means "unknown", not a crash
        recency = _unit(1.0 - (time.time() - float(created)) / 2592000)
        emotion_weight = _unit(sum(emu_weights.values()) / max(len(emu_weights), 1))
        surprise = _unit(surprise_delta)
        score = (0.4 * recency) + (0.3 * emotion_weight) + (0.3 * surprise)
        return round(score, 4)

    def rank(self, memories: list[dict]) -> list[dict]:
        return sorted(memories, key=lambda m: m.get("salience", 0), reverse=True)
