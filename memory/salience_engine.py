import time


class SalienceEngine:
    def score(self, memory: dict, emu_weights: dict, surprise_delta: float) -> float:
        recency = 1.0 - min(1.0, (time.time() - memory.get("created_at", time.time())) / 2592000)
        emotion_weight = sum(emu_weights.values()) / max(len(emu_weights), 1)
        surprise = min(1.0, surprise_delta)
        score = (0.4 * recency) + (0.3 * emotion_weight) + (0.3 * surprise)
        return round(score, 4)

    def rank(self, memories: list[dict]) -> list[dict]:
        return sorted(memories, key=lambda m: m.get("salience", 0), reverse=True)
