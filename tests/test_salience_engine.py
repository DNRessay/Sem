import time

from memory.salience_engine import SalienceEngine


def test_score_is_higher_for_recent_memories():
    engine = SalienceEngine()
    recent = engine.score({"created_at": time.time()}, {}, 0.0)
    old = engine.score({"created_at": time.time() - 2592000 * 2}, {}, 0.0)
    assert recent > old


def test_score_rewards_surprise_and_emotion_weight():
    engine = SalienceEngine()
    base = engine.score({"created_at": time.time()}, {}, 0.0)
    surprised = engine.score({"created_at": time.time()}, {"joy": 1.0}, 1.0)
    assert surprised > base


def test_rank_orders_descending_by_salience():
    engine = SalienceEngine()
    memories = [{"salience": 0.2}, {"salience": 0.9}, {"salience": 0.5}]
    ranked = engine.rank(memories)
    assert [m["salience"] for m in ranked] == [0.9, 0.5, 0.2]
