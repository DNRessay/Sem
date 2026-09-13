from cache import ddb_backend


class TAUCache:
    TTL_PROFILE = 3600
    NAMESPACE = "tau"

    def get(self, session_id: str) -> str | None:
        return ddb_backend.get(self.NAMESPACE, session_id)

    def set(self, session_id: str, ctx: str) -> None:
        ddb_backend.set(self.NAMESPACE, session_id, ctx, ttl=self.TTL_PROFILE)

    def invalidate(self, session_id: str) -> None:
        ddb_backend.delete(self.NAMESPACE, session_id)
