from storage.neon_store import get_store
from tau.pacific import PACIFICEngine
from tau.tau_cache import TAUCache


class TAUEngine:
    def __init__(self):
        self.pacific = PACIFICEngine()
        self.cache = TAUCache()
        self._session_counts: dict[str, int] = {}
        self._last_dream: dict[str, float] = {}

    async def observe_and_inject(self, session_id: str, query: str, history: list) -> str:
        cached = self.cache.get(session_id)
        if cached:
            return cached

        signals = self.pacific.infer_traits(history + [{"role": "user", "content": query}])
        db = await get_store()
        # SEMBLANCE has exactly one owner, not per-session users — the owner's profile
        # (name, projects, preferences) is seeded once under the fixed key "owner" and
        # should be known in every session, not just the one it happened to be saved in.
        # A session can still override individual fields (none do today).
        owner_profile = await db.get_user_model("owner") or {}
        session_model = await db.get_user_model(session_id) or {}
        user_model = {**owner_profile, **session_model}
        user_model["ocean"] = signals

        ctx = self._build_context(user_model, signals)
        self.cache.set(session_id, ctx)

        self._session_counts[session_id] = self._session_counts.get(session_id, 0) + 1
        return ctx

    def _build_context(self, user_model: dict, ocean: dict) -> str:
        parts = ["You are SEMBLANCE. You know this user well. Use everything below "
                 "without asking the user to repeat it."]
        if name := user_model.get("name"):
            parts.append(f"User's name: {name}")
        if location := user_model.get("location"):
            parts.append(f"Location: {location}")
        if about := user_model.get("about"):
            parts.append(f"About them: {about}")
        if goals := user_model.get("goals"):
            joined = ", ".join(goals) if isinstance(goals, list) else goals
            parts.append(f"Goals: {joined}")
        if comm := user_model.get("communication_style"):
            parts.append(f"Communication style to match: {comm}")
        if coding := user_model.get("coding_preferences"):
            parts.append(f"Coding preferences: {coding}")
        if envs := user_model.get("environments"):
            joined = ", ".join(envs) if isinstance(envs, list) else envs
            parts.append(f"Dev environments: {joined}")
        if skills := user_model.get("skills"):
            parts.append(f"Skills/stack: {', '.join(skills)}")
        if projects := user_model.get("projects"):
            parts.append(f"Active projects: {', '.join(projects)}")
        if interests := user_model.get("interests"):
            parts.append(f"Interests: {', '.join(interests)}")
        if ocean:
            o = ocean
            parts.append(
                f"User personality (OCEAN): O={o.get('O',0.5):.2f} "
                f"C={o.get('C',0.5):.2f} E={o.get('E',0.5):.2f} "
                f"A={o.get('A',0.5):.2f} N={o.get('N',0.5):.2f}"
            )
        if prefs := user_model.get("preferences"):
            parts.append(f"Known preferences: {prefs}")
        return "\n".join(parts)

    def trigger_dream_if_ready(self, session_id: str) -> bool:
        import time
        now = time.time()
        last = self._last_dream.get(session_id, 0)
        sessions = self._session_counts.get(session_id, 0)
        if (now - last) >= 86400 and sessions >= 5:
            self._last_dream[session_id] = now
            return True
        return False
