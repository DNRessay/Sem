from cache import ddb_backend

WRITE_COST_5MIN = 1.25
WRITE_COST_1HR = 2.0
READ_COST = 0.10


class SysCache:
    """Caches SEMBLANCE.md + tool registry. DynamoDB-backed, L1 in-memory."""

    NAMESPACE = "sys"

    def warm(self):
        from pipeline.ctx_assembly import CTXAssembly
        ctx = CTXAssembly().load_hierarchy()
        self.write("system_prompt", ctx, ttl=3600)

    def write(self, key: str, value: str, ttl: int = 300):
        ddb_backend.set(self.NAMESPACE, key, value, ttl=ttl)

    def read(self, key: str) -> str | None:
        return ddb_backend.get(self.NAMESPACE, key)


class ConvCache:
    """Rolling conversation cache, up to 4 breakpoints, 20-block lookback."""

    MAX_BREAKPOINTS = 4
    LOOKBACK = 20
    NAMESPACE = "conv"
    TTL = 3600

    def append(self, session_id: str, turn: dict):
        turns = self._load(session_id)
        turns.append(turn)
        if len(turns) > self.LOOKBACK:
            turns.pop(0)
        self._save(session_id, turns)

    def get_window(self, session_id: str) -> list:
        return self._load(session_id)[-self.LOOKBACK:]

    def _load(self, session_id: str) -> list:
        import json
        raw = ddb_backend.get(self.NAMESPACE, session_id)
        return json.loads(raw) if raw else []

    def _save(self, session_id: str, turns: list) -> None:
        import json
        ddb_backend.set(self.NAMESPACE, session_id, json.dumps(turns), ttl=self.TTL)
