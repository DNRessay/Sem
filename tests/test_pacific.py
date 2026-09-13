from tau.pacific import PACIFICEngine


def test_infer_traits_neutral_history_defaults_to_midpoint():
    engine = PACIFICEngine()
    traits = engine.infer_traits([])
    assert traits == {"O": 0.5, "C": 0.5, "E": 0.5, "A": 0.5, "N": 0.5}


def test_infer_traits_picks_up_conscientiousness_signals():
    engine = PACIFICEngine()
    history = [
        {"role": "user", "content": "I need a schedule and a deadline for this plan"},
    ]
    traits = engine.infer_traits(history)
    assert traits["C"] > 0.5


def test_get_personalization_vector_is_ordered_OCEAN():
    engine = PACIFICEngine()
    traits = {"O": 0.1, "C": 0.2, "E": 0.3, "A": 0.4, "N": 0.5}
    assert engine.get_personalization_vector(traits) == [0.1, 0.2, 0.3, 0.4, 0.5]
