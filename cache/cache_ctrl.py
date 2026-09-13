import hashlib

from cache import ddb_backend

BREAK_VECTORS = [
    "tool_change", "model_switch", "image_added", "system_prompt_edit",
    "user_model_update", "trust_level_change", "new_agent_spawned",
    "memory_consolidation", "ctx_length_exceeded", "tool_error",
    "session_restart", "provider_switch", "mcp_server_change", "manual_flush",
]


class CacheController:
    NAMESPACE = "ctrl"

    def __init__(self):
        self._fired: set[str] = set()

    def compute_prefix_hash(self, prefix: str) -> str:
        return hashlib.sha256(prefix.encode()).hexdigest()

    def is_cache_valid(self, key: str, ttl: int = 300) -> bool:
        return ddb_backend.get(self.NAMESPACE, key) is not None

    def write(self, key: str, value: str, ttl: int = 300):
        ddb_backend.set(self.NAMESPACE, key, value, ttl=ttl)

    def read(self, key: str) -> str | None:
        return ddb_backend.get(self.NAMESPACE, key)

    def invalidate(self, reason: str):
        if reason in BREAK_VECTORS:
            self._fired.add(reason)
            ddb_backend.clear_namespace(self.NAMESPACE)

    def check_break(self) -> bool:
        return bool(self._fired)

    def reset_breaks(self):
        self._fired.clear()
