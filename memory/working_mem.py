from cache import ddb_backend


class WorkingMem:
    """Per-session scratch reasoning (QueryEngine.connector_text_buffer).
    Kept in the DynamoDB cache for an hour so it survives between Lambda
    invocations instead of living in one container's RAM."""

    NAMESPACE = "working_mem"
    TTL_SECONDS = 3600
    MAX_CHARS = 20_000

    def append(self, session_id: str, reasoning: str):
        current = ddb_backend.get(self.NAMESPACE, session_id) or ""
        updated = f"{current}\n{reasoning}" if current else reasoning
        ddb_backend.set(self.NAMESPACE, session_id, updated[-self.MAX_CHARS:], ttl=self.TTL_SECONDS)

    def get(self, session_id: str) -> str:
        return ddb_backend.get(self.NAMESPACE, session_id) or ""

    def clear(self, session_id: str):
        ddb_backend.delete(self.NAMESPACE, session_id)
