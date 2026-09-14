import random
import time

from agents.base_agent import BaseAgent

SPECIES = [
    "Foxbyte",   "Glitchcat", "Neonbat",   "Sparkcub",  "Emberwolf",
    "Frostpup",  "Stormhare", "Voidferret","Lumibear",  "Driftbird",
    "Cipherowl", "Flickrat",  "Phasedeer", "Quartzfox", "Tesselmole",
    "Aurabug",   "Mirrorfish","Echosnake",
]

RARITIES = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
RARITY_WEIGHTS = [50, 25, 15, 8, 2]

MOODS = ["playful", "curious", "sleepy", "energetic", "focused", "calm"]


class Buddy:
    def __init__(self, species: str = None, name: str = None):
        self.species  = species or random.choice(SPECIES)
        self.name     = name or f"{self.species}_{random.randint(100,999)}"
        self.rarity   = random.choices(RARITIES, weights=RARITY_WEIGHTS, k=1)[0]
        self.mood     = random.choice(MOODS)
        self.level    = 1
        self.xp       = 0
        self.xp_next  = 100
        self.hp       = 100
        self.born_at  = time.time()
        self.last_fed = time.time()
        self.stats    = {"energy": 80, "happiness": 90, "focus": 70}

    def interact(self, action: str) -> str:
        if action == "pet":
            self.stats["happiness"] = min(100, self.stats["happiness"] + 5)
            return f"{self.name} purrs happily! 💛"
        elif action == "feed":
            self.stats["energy"] = min(100, self.stats["energy"] + 20)
            self.last_fed = time.time()
            self.gain_xp(10)
            return f"{self.name} munches eagerly! +10 XP 🍖"
        elif action == "train":
            self.stats["focus"] = min(100, self.stats["focus"] + 10)
            self.gain_xp(25)
            return f"{self.name} trains hard! +25 XP 💪"
        elif action == "play":
            self.mood = "playful"
            self.stats["happiness"] = min(100, self.stats["happiness"] + 10)
            self.gain_xp(15)
            return f"{self.name} bounces with joy! +15 XP ✨"
        else:
            return f"{self.name} tilts its head curiously."

    def gain_xp(self, amount: int):
        self.xp += amount
        if self.xp >= self.xp_next:
            self.level += 1
            self.xp -= self.xp_next
            self.xp_next = int(self.xp_next * 1.5)
            self.hp = min(150, self.hp + 10)

    def status(self) -> dict:
        hours_since_fed = (time.time() - self.last_fed) / 3600
        if hours_since_fed > 8:
            self.stats["energy"] = max(0, self.stats["energy"] - 10)

        return {
            "name": self.name,
            "species": self.species,
            "rarity": self.rarity,
            "mood": self.mood,
            "level": self.level,
            "xp": self.xp,
            "xp_next": self.xp_next,
            "hp": self.hp,
            "stats": self.stats,
            "hours_since_fed": round(hours_since_fed, 1),
        }

    def to_dict(self) -> dict:
        return {**self.status(), "born_at": self.born_at, "last_fed": self.last_fed}


class BuddyAgent(BaseAgent):
    """
    Tamagotchi-style companion agent.
    18 species, rarity tiers, stats.
    One buddy per session — persists across turns.
    """

    def __init__(self, tools_registry=None, cables_man_ref=None, **kwargs):
        super().__init__(tools_registry, cables_man_ref, **kwargs)
        self._buddies: dict[str, Buddy] = {}

    async def run(self, task: dict) -> dict:
        session  = task.get("session_id", "default")
        action   = task.get("action", "status")

        buddy = self._get_or_create(session)
        self.log_audit(f"buddy:{session}:{action}")

        if action == "status":
            return buddy.status()
        elif action in ("pet", "feed", "train", "play"):
            message = buddy.interact(action)
            return {"message": message, "status": buddy.status()}
        elif action == "rename":
            buddy.name = task.get("name", buddy.name)
            return {"message": f"Renamed to {buddy.name}!", "status": buddy.status()}
        elif action == "new":
            self._buddies[session] = Buddy(
                species=task.get("species"),
                name=task.get("name"),
            )
            return {"message": f"New buddy {self._buddies[session].name} hatched!", "status": self._buddies[session].status()}
        else:
            return {"error": f"Unknown buddy action: {action}"}

    def _get_or_create(self, session_id: str) -> Buddy:
        if session_id not in self._buddies:
            self._buddies[session_id] = Buddy()
        return self._buddies[session_id]

    def get_all_species(self) -> list[str]:
        return SPECIES
