from storage.neon_store import get_store
from tau.emotion_engine import NatureSCIEngine
from tau.pacific import PACIFICEngine
from tau.tau_cache import TAUCache


class TAUEngine:
    def __init__(self):
        self.pacific = PACIFICEngine()
        self.emotion = NatureSCIEngine()
        self.cache = TAUCache()

    async def observe_and_inject(self, session_id: str, query: str, history: list) -> str:
        """The cached profile context plus this turn's emotional read — the
        tone line is per message, so it's never part of the cached block."""
        emu = await self.emotion.classify(query)
        tone = self.emotion.guidance(emu)
        ctx = self.cache.get(session_id) or await self._profile_context(session_id, query, history)
        return f"{ctx}\nTone for this reply: {tone}" if tone else ctx

    async def _profile_context(self, session_id: str, query: str, history: list) -> str:
        db = await get_store()
        # SEMBLANCE has exactly one owner, not per-session users — the owner's profile
        # (name, projects, preferences) is seeded once under the fixed key "owner" and
        # should be known in every session, not just the one it happened to be saved in.
        # A session can still override individual fields (none do today).
        owner_profile = await db.get_user_model("owner") or {}
        session_model = await db.get_user_model(session_id) or {}
        user_model = {**owner_profile, **session_model}
        # The daily PACIFIC refresh (tau/pacific.py, run from the tick) saves an
        # LLM-read profile across all conversations; the keyword estimate from
        # this one conversation is only the fallback until that has run.
        ocean = owner_profile.get("ocean") or self.pacific.infer_traits(history + [{"role": "user", "content": query}])

        ctx = self._build_context(user_model, ocean)
        self.cache.set(session_id, ctx)
        return ctx

    async def owner_context(self) -> str:
        """The owner's saved profile for the tool agents (Code, Co-work, …),
        so they know who they're working for."""
        try:
            db = await get_store()
            profile = await db.get_user_model("owner") or {}
        except Exception:  # no profile is better than a failed agent run
            return ""
        return self._build_context(profile, profile.get("ocean") or {}) if profile else ""

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
        if observed := user_model.get("observed_style"):
            parts.append(f"How they like answers (observed over time): {observed}")
        if prefs := user_model.get("preferences"):
            parts.append(f"Known preferences: {prefs}")
        return "\n".join(parts)
