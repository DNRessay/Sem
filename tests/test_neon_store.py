from storage.neon_store import _to_vector_literal


def test_to_vector_literal_none_and_empty_return_none():
    assert _to_vector_literal(None) is None
    assert _to_vector_literal([]) is None


def test_to_vector_literal_formats_pgvector_syntax():
    literal = _to_vector_literal([0.1, 0.2, -0.3])
    assert literal.startswith("[") and literal.endswith("]")
    assert literal == "[0.10000000,0.20000000,-0.30000000]"
