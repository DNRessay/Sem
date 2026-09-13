from tools.registry import get_registry


def test_get_registry_bootstraps_without_crashing():
    # tools/registry.py imports every built-in tool module at first use;
    # a missing module here has previously crashed every code path that
    # touches the registry (pipeline/tool_execution.py, core/cables_man.py).
    registry = get_registry()
    names = registry.list_all()
    assert "bash" in names
    assert "calendar" in names
    assert "whatsapp" in names


def test_execute_unknown_tool_returns_error_not_exception():
    registry = get_registry()
    import asyncio
    result = asyncio.run(registry.execute("not_a_real_tool", {}))
    assert "error" in result
