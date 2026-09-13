class WorkingMem:
    def __init__(self):
        self._store: dict[str, list[str]] = {}

    def append(self, session_id: str, reasoning: str):
        self._store.setdefault(session_id, []).append(reasoning)

    def get(self, session_id: str) -> str:
        return "\n".join(self._store.get(session_id, []))

    def clear(self, session_id: str):
        self._store.pop(session_id, None)
