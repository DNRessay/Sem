from tau.emotion_engine import NatureSCIEngine


def test_analyse_text_detects_joy():
    engine = NatureSCIEngine()
    emu = engine.analyse_text("This is awesome, I'm so excited and thrilled!")
    assert emu.label == "joy"
    assert emu.valence > 0


def test_analyse_text_defaults_to_neutral():
    engine = NatureSCIEngine()
    emu = engine.analyse_text("The meeting is at 3pm.")
    assert emu.label == "neutral"


def test_modulate_prompt_adds_empathetic_tone_for_negative_valence():
    engine = NatureSCIEngine()
    emu = engine.analyse_text("I'm so sad and disappointed about this")
    prompt = engine.modulate_prompt("base", emu)
    assert "empathetic" in prompt


def test_track_sequence_reports_dominant_emotion():
    engine = NatureSCIEngine()
    history = [
        {"role": "user", "content": "I'm so happy and excited"},
        {"role": "user", "content": "this is great, I love it"},
    ]
    result = engine.track_sequence(history)
    assert result["dominant"] == "joy"
