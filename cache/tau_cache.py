from cache import ddb_backend


class TAUCache:
    TTL_PROFILE = 3600
    NAMESPACE = "tau"

    # Bumped when the owner edits their profile in Settings, so every session's
    # cached profile context goes stale at once (DynamoDB has no prefix delete).
    def _key(self, session_id: str) -> str:
        # fresh: a bump on another Lambda instance must be seen on the next message, not after this copy's
        # year-long TTL runs out.
        return f"{session_id}:{ddb_backend.get(self.NAMESPACE, '_version', fresh=True) or '0'}"

    def bump_version(self) -> None:
        import time
        ddb_backend.set(self.NAMESPACE, "_version", str(int(time.time())), ttl=365 * 86400)

    def get(self, session_id: str) -> str | None:
        return ddb_backend.get(self.NAMESPACE, self._key(session_id))

    def set(self, session_id: str, ctx: str) -> None:
        ddb_backend.set(self.NAMESPACE, self._key(session_id), ctx, ttl=self.TTL_PROFILE)

    def invalidate(self, session_id: str) -> None:
        ddb_backend.delete(self.NAMESPACE, self._key(session_id))
