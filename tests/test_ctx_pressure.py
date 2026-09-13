from pipeline.ctx_pressure import SUMMARY_TARGET, CTXPressure


def test_short_context_passes_through_unchanged():
    ctx = "short context"
    assert CTXPressure().apply(ctx) == ctx


def test_long_context_is_compacted_to_target():
    ctx = "line\n" * 10_000  # far over SUMMARY_TARGET
    result = CTXPressure().apply(ctx)
    assert len(result) <= SUMMARY_TARGET


def test_collapse_deduplicates_lines():
    ctx = "a\nb\na\nb\nc"
    assert CTXPressure().collapse(ctx) == "a\nb\nc"
