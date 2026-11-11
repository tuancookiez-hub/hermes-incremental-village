"""Deterministic Stone Age village rules.

The engine is the only source of truth for time, position, energy, skills and
resources. Plans (from the model or from habit) are *requests*: every action is
validated here and either executed or rejected with a reason the villager will
read the next day. Nothing in this module talks to a model or to storage.

The village lives on a clock without any background process. A day is resolved
in full when it starts, and each step records when it happens and what it
changed, so the Desktop page can play the day back. ``advance`` catches the
clock up lazily whenever someone looks; days nobody watched run the same way.
"""
from __future__ import annotations

import math
import random
from collections import Counter, deque
from functools import lru_cache
from typing import Any

SCHEMA_VERSION = 10
DAY_SECONDS = 120             # real seconds per in-game day
DAWN_FRACTION = 0.1           # the day opens with villagers asleep as the sun comes up
WALK_PER_SLOT = 3
HOME_REACH = 12               # further than this and a villager camps out rather than walking back
WORK_FRACTION = 0.8           # work ends here; dusk and night fill the rest, so night runs into dawn
MAX_CATCHUP_DAYS = 200        # days simulated for one absence; the rest are skipped
SPEEDS = (1, 2, 4, 8, 16)     # how fast the clock runs while someone is watching
SPEED_IDLE_SECONDS = 30       # no reads for this long means nobody is watching: back to 1x
CHUNK = 16                     # land is made and sent in squares this wide; a village walks 24 tiles a day at most
CAMP: tuple[int, int] | None = None  # None finds open land near the middle of the seed's world
CAMP_CLEARING = 3              # the first camp is on dry ground this far out in every direction
CAMP_WATER = 6                 # and has real water within this many tiles
CLIMATE_PULL = 0.3             # how far a region's climate shifts its land
WATER_BELOW = 0.337           # calibrated over 160,000 samples: about 13% water, 10% rock, 34% forest
ROCK_ABOVE = 0.684
FOREST_ABOVE = 0.562
BERRIES_ABOVE = 0.77
SEARCH_REACH = 40              # how far a villager's instincts look for what they want
SLOTS_PER_DAY = 8
VISION = 4
TALK_RANGE = 2
MAX_ACTIONS = 6
MAX_ENERGY = 10
OVERNIGHT_ENERGY = 4          # spike showed +2 starved villagers by day 9
HUNGRY_ENERGY = 2             # overnight recovery without a meal
MEMORY_LINES = 4
HEARD_LINES = 3
MAX_VILLAGERS = 6
MAX_HEALTH = 5
SEASON_DAYS = 5               # four seasons, so a year is 20 days
SEASONS = ("spring", "summer", "autumn", "winter")
BUSH_FOOD = 4                 # food on a full bush tile
TREE_WOOD = 3                 # wood in a forest tile. A cleared tile only returns as young trees seed from a neighbour
TREE_REGROW_DAYS = 6          # a part-cut forest tile regrows 1 wood every this many days, except in winter
SEEDING_CHANCE = 0.4          # each spring, a cleared tile beside living forest may take young trees
WOODLOT_GROW_DAYS = 4         # a tended woodlot regrows 1 wood this often: real coppice, sped up to game years
CARRY_LIMIT = 12              # what one villager can carry; stone counts double
PACK_FRAME_BONUS = 6
WEIGHTS = {"stone": 2}
STORE_REACH = 2               # how close to stand to put in or take out
BUILD_REACH = 5               # builders this close to the store can draw on it
FIRE_FUEL_REACH = 6           # a fire draws on a store this close
WATER_RANGE = 7               # sleep this far from water and you must carry some
SOIL_LOSS = 0.12              # each harvest wears a field; resting it restores the soil
SOIL_REST = 0.03
EDIBLE = ("meat", "food", "grain")
HUNT_REACH = 2
HUNT_SLOTS = 3
MEAT_PER_KILL = 6
GORE_DAMAGE = 2
HERD_LIMIT = 6
HERD_CHANCE = 0.67             # share of chunks that hold a herd when first seen
ANIMALS = {"deer": {"odds": 0.55, "gore": 0.0}, "boar": {"odds": 0.45, "gore": 0.25}}
BUSH_REGROW_DAYS = 3          # a bush regrows 1 food every this many days, except in winter
FIELD_FOOD = 8
FIELD_GROWTH = 2              # a field grows this much a day, except in winter
ROT_SHARE = 4                 # each night 1 in this many carried food rots, unless there is a drying rack
ROT_BY_ITEM = {"meat": 2, "food": ROT_SHARE}  # grain keeps; meat turns fastest
SHELTER_RANGE = 5             # how close shelter or fire must be to count at night
WOLF_CHANCE = 0.05            # chance per night outside fire range
WOLF_BITE = 2
EMPTIED_FOR_FARMING = 4       # bushes picked bare before someone notices the seeds sprouting
FIELD_WATER_RANGE = 3
START_TRUST = 50
TRUST_HEEDED = 40             # below this, free days ignore the guide's focus
TRUST_EAGER = 70
FOCUS_DAYS = 5                # how long advice runs before the game judges it
EXPERIMENT_SLOTS = 3
FOCUSES = {
    "food": "keep everyone fed",
    "shelter": "build homes",
    "explore": "see what is out there",
    "learn": "try the new ideas",
}
# What the guide can plant. Costs are Insight. The order follows real history;
# the villagers still have to test each idea themselves with ``experiment``.
IDEAS: dict[str, dict[str, Any]] = {
    "coppicing": {"name": "Coppicing", "era": "Stone Age", "cost": 4, "needs": [], "try": {"wood": 1}, "near": None,
                  "skill": None, "hint": "a cut tree sends up new shoots from its stump if it is left to grow",
                  "unlocks": "woodlots", "history": "Tended woodland was cut in rotation for thousands of years."},
    "sowing": {"name": "Sowing", "era": "Stone Age", "cost": 5, "needs": [], "try": {"food": 1}, "near": "water",
               "skill": "farming", "hint": "seeds dropped in damp ground come up where you left them",
               "unlocks": "fields", "history": "Farming began about 12,000 years ago."},
    "pottery": {"name": "Pottery", "era": "Farming Age", "cost": 7, "needs": ["sowing"], "try": {"wood": 1}, "near": "fire",
                "skill": None, "hint": "wet clay hardens in a hot fire, and a sealed pot keeps food from spoiling",
                "unlocks": "storehouse", "history": "Fired clay pots are older than farming in parts of Asia."},
    "masonry": {"name": "Masonry", "era": "Farming Age", "cost": 9, "needs": ["pottery"], "try": {"stone": 2}, "near": None,
                "skill": None, "hint": "stones stacked with care make walls that outlast wood",
                "unlocks": "stone house", "history": "Stone settlements followed the first farms."},
    "copper": {"name": "Copper", "era": "Copper Age", "cost": 14, "needs": ["pottery"], "try": {"stone": 2, "wood": 2}, "near": "fire",
               "skill": None, "hint": "green stones melt in a fierce fire, and the metal holds an edge",
               "unlocks": "metal tools: 1 more wood or stone per gather",
               "history": "Pottery kilns gave people the heat that smelting needs."},
    "fishing": {"name": "Fishing", "era": "Stone Age", "cost": 4, "needs": [], "try": {"wood": 1}, "near": "water",
                "skill": None, "hint": "a sharpened stick and patience take fish from the shallows",
                "unlocks": "the folk fish any water in reach", "boost": {"fish": 1},
                "history": "Shell hooks from Okinawa are about 23,000 years old."},
    "plough": {"name": "The plough", "era": "Farming Age", "cost": 10, "needs": ["sowing"], "try": {"wood": 2}, "near": None,
               "skill": None, "hint": "a forked branch dragged through the soil opens it for seed",
               "unlocks": "fields give twice the food", "boost": {"food": 2},
               "history": "Scratch ploughs were in use by 4000 BC."},
    "irrigation": {"name": "Irrigation", "era": "Farming Age", "cost": 12, "needs": ["sowing"], "try": {"wood": 1}, "near": "water",
                   "skill": None, "hint": "a ditch carries the river to dry ground",
                   "unlocks": "fields up to 9 tiles from water", "boost": {"water_range": 6},
                   "history": "Mesopotamian farmers dug canals from about 6000 BC."},
    "longhouse": {"name": "Longhouses", "era": "Farming Age", "cost": 10, "needs": ["sowing"], "try": {"wood": 2}, "near": None,
                  "skill": None, "hint": "one long roof shelters many families at once",
                  "unlocks": "every home holds twice as many", "boost": {"housing": 2},
                  "history": "Neolithic longhouses in Europe were up to 45 metres long."},
    "herding": {"name": "Herding", "era": "Farming Age", "cost": 14, "needs": ["sowing"], "try": {"food": 2}, "near": None,
                "skill": None, "hint": "young animals raised by hand stay near the people who feed them",
                "unlocks": "half as much food again", "boost": {"food": 1.5},
                "history": "Sheep and goats were domesticated about 10,000 years ago."},
    "wheel": {"name": "The wheel", "era": "Copper Age", "cost": 20, "needs": ["copper"], "try": {"wood": 2}, "near": None,
              "skill": None, "hint": "a log rolls where a sledge drags",
              "unlocks": "the folk work half as fast again, and range further", "boost": {"work": 1.5, "reach": 1.5},
              "history": "The oldest known wheels are from about 3500 BC."},
    "bronze": {"name": "Bronze", "era": "Bronze Age", "cost": 30, "needs": ["copper"], "try": {"stone": 2, "wood": 2}, "near": "fire",
               "skill": None, "hint": "copper melted with tin is harder than either",
               "unlocks": "the folk work twice as fast", "boost": {"work": 2},
               "history": "Bronze spread across Eurasia from about 3300 BC."},
    "writing": {"name": "Writing", "era": "Bronze Age", "cost": 40, "needs": ["bronze"], "try": {"wood": 1}, "near": None,
                "skill": None, "hint": "marks pressed in clay remember what was owed",
                "unlocks": "twice the Insight, and homes hold half as many again", "boost": {"insight": 2, "housing": 1.5},
                "history": "Sumerian tallies became writing around 3200 BC."},
    "iron": {"name": "Iron", "era": "Iron Age", "cost": 60, "needs": ["bronze"], "try": {"stone": 3, "wood": 2}, "near": "fire",
             "skill": None, "hint": "red earth gives a grey metal in a hotter fire, and it is everywhere",
             "unlocks": "twice the work and twice the food", "boost": {"work": 2, "food": 2},
             "history": "Iron smelting was common by 1200 BC."},
    "roads": {"name": "Roads", "era": "Iron Age", "cost": 50, "needs": ["wheel", "bronze"], "try": {"stone": 3}, "near": None,
              "skill": None, "hint": "stones laid flat make a way that carts can use in the rain",
              "unlocks": "the folk range twice as far", "boost": {"reach": 2},
              "history": "Paved roads joined cities long before Rome made them famous."},
    "aqueduct": {"name": "Aqueducts", "era": "Iron Age", "cost": 80, "needs": ["masonry", "iron"], "try": {"stone": 4}, "near": "water",
                 "skill": None, "hint": "a stone channel carries clean water into the streets",
                 "unlocks": "homes hold three times as many", "boost": {"housing": 3},
                 "history": "Clean water let ancient cities pass a hundred thousand people."},
    "steam": {"name": "Steam", "era": "Steam Age", "cost": 150, "needs": ["iron"], "try": {"wood": 4, "stone": 2}, "near": "fire",
              "skill": None, "hint": "boiling water pushes harder than any ox",
              "unlocks": "the folk work four times as fast", "boost": {"work": 4},
              "history": "Steam engines drove the Industrial Revolution from the 1700s."},
    "steel": {"name": "Steel", "era": "Steel Age", "cost": 300, "needs": ["steam"], "try": {"stone": 4, "wood": 4}, "near": "fire",
              "skill": None, "hint": "iron blown through with air holds up towers",
              "unlocks": "homes hold four times as many, and three times the food", "boost": {"housing": 4, "food": 3},
              "history": "Steel frames made the first skyscrapers possible in the 1880s."},
    "flight": {"name": "Flight", "era": "Age of Flight", "cost": 1000, "needs": ["steel"], "try": {"wood": 4, "stone": 4}, "near": None,
               "skill": None, "hint": "a wing shaped like a bird's lifts when the wind runs over it",
               "unlocks": "they leave the ground", "boost": {"work": 2},
               "history": "The first powered flight was in 1903."},
}
IDEAS["copper"]["boost"] = {"work": 1.5}
ERAS = ("Stone Age", "Farming Age", "Copper Age", "Bronze Age", "Iron Age", "Steam Age", "Steel Age", "Age of Flight")
FUTURE_ERAS = ERAS[3:]

# The folk: everyone in the village who is not one of its named villagers. They are a number. They
# live in the homes that have been built, work the land around the store, eat from it and have
# children when it is full. Every tile they strip is a real tile.
FOLK_HOMES = {"lean_to": 1, "hut": 4, "stone_house": 10}  # how many each building houses
FOLK_REACH = 8                 # tiles from the store they work at first; it widens as they multiply
FOLK_BIRTH_RATE = 0.07         # of the folk, each well-fed day there is room
FOLK_STARVE_SHARE = 0.25       # of those who went without food, each day
FOLK_LARDER = {"spring": 4, "summer": 5, "autumn": 9, "winter": 3}  # days of food worth gathering for
FOLK_BUILDS = ("hut", "stone_house", "field", "woodlot", "fire_pit", "storehouse")
FOLK_MILESTONES = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000)
UPGRADES: dict[str, dict[str, Any]] = {
    "long_memory": {"name": "Long memory", "cost": 4, "effect": "villagers keep 2 more notes"},
    "patient_teaching": {"name": "Patient teaching", "cost": 5, "effect": "teaching takes half the time"},
    "pack_frames": {"name": "Pack frames", "cost": 6, "effect": f"villagers carry {PACK_FRAME_BONUS} more"},
    "keen_eyes": {"name": "Keen eyes", "cost": 6, "effect": "villagers see 1 tile further"},
    "hardy": {"name": "Hardy bodies", "cost": 8, "effect": "1 more health"},
}
PERKS: dict[str, dict[str, Any]] = {
    "full_packs": {"name": "Full packs", "cost": 2, "effect": "new villages start with 2 extra food each"},
    "first_trust": {"name": "Old friends", "cost": 2, "effect": "new villages start at 65 Trust"},
    "old_songs": {"name": "Old songs", "cost": 3, "effect": "new villages start with 5 Insight"},
    "seed_memory": {"name": "Seed memory", "cost": 6, "effect": "new villages already know sowing"},
}
WANDERERS = ("Dara", "Ewan", "Fenn", "Gwen", "Hale", "Ivo", "Juno", "Kell", "Lorn", "Mira", "Nell", "Odo")

TERRAIN = ("grass", "forest", "rock", "berries", "water")
TILE_CHARS = {"grass": ".", "forest": "T", "rock": "R", "berries": "b", "water": "~"}
YIELD = {"forest": "wood", "rock": "stone", "berries": "food", "water": "water"}
ITEMS = ("wood", "stone", "food", "grain", "meat", "water")
SKILLS = ("firemaking", "weaving", "foraging", "farming")

# name -> cost, required skill, slots, how many may exist, what it does
BUILDINGS: dict[str, dict[str, Any]] = {
    "lean_to": {"cost": {"wood": 4}, "skill": None, "slots": 3, "max": 6, "rest": 1,
                "effect": "everyone recovers 1 more energy overnight"},
    "fire_pit": {"cost": {"stone": 3, "wood": 1}, "skill": "firemaking", "slots": 2, "max": 12, "rest": 1,
                 "effect": "everyone recovers 1 more energy overnight"},
    "drying_rack": {"cost": {"wood": 3}, "skill": "weaving", "slots": 3, "max": 1, "food": 1,
                    "effect": "gathering food yields 1 more, and carried food stops rotting"},
    "field": {"cost": {"wood": 2}, "skill": "farming", "slots": 2, "max": 120, "near_water": FIELD_WATER_RANGE,
              "effect": "grows grain, which keeps all winter; must be near water, and tires if never rested"},
    "woodlot": {"cost": {"wood": 2}, "skill": None, "idea": "coppicing", "slots": 2, "max": 30,
                "effect": f"tended stumps give back 1 wood every {WOODLOT_GROW_DAYS} days"},
    "depot": {"cost": {"wood": 2}, "skill": None, "slots": 2, "max": 8,
              "effect": "a cache far from camp: store goods here instead of hauling them all the way back"},
    "hut": {"cost": {"wood": 6, "stone": 2}, "skill": None, "slots": 4, "max": 60,
            "effect": "a proper home: 2 beds for villagers and room for 4 of the folk"},
    "storehouse": {"cost": {"wood": 4, "stone": 2}, "skill": None, "idea": "pottery", "slots": 3, "max": 1,
                   "effect": f"food stops rotting for anyone sleeping within {SHELTER_RANGE} tiles"},
    "stone_house": {"cost": {"stone": 6, "wood": 2}, "skill": None, "idea": "masonry", "slots": 5, "max": 80,
                    "effect": "a lasting home: 3 beds for villagers and room for 10 of the folk"},
}
LEVELS = ((0, "Camp"), (2, "Hamlet"), (4, "Village"))
TOWNS = ((150, "Town"), (1000, "City"), (10000, "Metropolis"))  # past a village, it is people that count

VERBS = ("look", "walk", "gather", "build", "talk", "trade", "teach", "rest", "experiment", "deposit", "take", "hunt")

STARTING_VILLAGERS = (
    {"name": "Ash", "skills": ["firemaking"], "trait": "cautious, protective of the group"},
    {"name": "Bryn", "skills": ["weaving"], "trait": "curious, wanders to see what is over the hill"},
    {"name": "Coll", "skills": ["foraging"], "trait": "practical, hungry, a little stubborn"},
)


def dist(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


# ---------------------------------------------------------------- world creation

def _lattice(seed: int, x: int, y: int) -> float:
    h = (x * 374761393 + y * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) % 100000) / 100000


def _noise(seed: int, x: float, y: float) -> float:
    xi, yi = int(x // 1), int(y // 1)
    u, v = x - xi, y - yi
    u, v = u * u * (3 - 2 * u), v * v * (3 - 2 * v)
    top = _lattice(seed, xi, yi) * (1 - u) + _lattice(seed, xi + 1, yi) * u
    low = _lattice(seed, xi, yi + 1) * (1 - u) + _lattice(seed, xi + 1, yi + 1) * u
    return top * (1 - v) + low * v


def _layered(seed: int, x: float, y: float, octaves: int = 4) -> float:
    total, amp, scale = 0.0, 0.5, 1.0
    for i in range(octaves):
        total += _noise(seed + i * 101, x * scale, y * scale) * amp
        amp *= 0.5
        scale *= 2.03
    return total / (1 - 0.5 ** octaves)


def _climate(seed: int, x: float, y: float) -> tuple[float, float]:
    """Slow-changing rise and moisture: days of walking turn plains into highlands or deep forest."""
    return _layered(seed + 31, x / 150, y / 150, 2), _layered(seed + 37, x / 110, y / 110, 2)


@lru_cache(maxsize=4096)
def _land(seed: int, cx: int, cy: int) -> tuple[str, ...]:
    """One chunk of untouched land. It is a pure function of the seed and the position, so
    the world has no edge, and land nobody has changed never needs saving."""
    x0, y0 = cx * CHUNK, cy * CHUNK
    corners = [_climate(seed, x0 + a * CHUNK, y0 + b * CHUNK) for b in (0, 1) for a in (0, 1)]
    rows = []
    for dy in range(CHUNK):
        v, y, row = dy / CHUNK, y0 + dy, []
        for dx in range(CHUNK):
            u, x = dx / CHUNK, x0 + dx
            top = [corners[0][i] * (1 - u) + corners[1][i] * u for i in (0, 1)]
            low = [corners[2][i] * (1 - u) + corners[3][i] * u for i in (0, 1)]
            rise, moist = (top[i] * (1 - v) + low[i] * v for i in (0, 1))
            height = _layered(seed, x / 13, y / 13) + (rise - 0.5) * CLIMATE_PULL
            if height < WATER_BELOW:
                row.append("~")
            elif height > ROCK_ABOVE:
                row.append("R")
            elif _layered(seed + 7, x / 9, y / 9) + (moist - 0.5) * CLIMATE_PULL > FOREST_ABOVE:
                row.append("T")
            elif _noise(seed + 13, x / 2.7, y / 2.7) > BERRIES_ABOVE:
                row.append("b")
            else:
                row.append(".")
        rows.append("".join(row))
    return tuple(rows)


def _land_char(seed: int, x: int, y: int) -> str:
    return _land(seed, x >> 4, y >> 4)[y & 15][x & 15]


def _open_country(seed: int, x: int, y: int, reach: int) -> bool:
    """Land runs on from here for at least ``reach`` tiles, so a band is not stranded on a spit."""
    done, queue = {(x, y)}, deque([(x, y)])
    while queue:
        cx, cy = queue.popleft()
        if dist(cx, cy, x, y) >= reach:
            return True
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if (nx, ny) not in done and _land_char(seed, nx, ny) != "~":
                done.add((nx, ny))
                queue.append((nx, ny))
    return False


def _find_camp(seed: int) -> tuple[int, int]:
    """The closest place to the middle of this world where people would stop: dry ground
    within a short walk of real water, with land running on beyond it."""
    def suits(x: int, y: int) -> bool:
        ring = [(dx, dy) for dy in range(-CAMP_WATER, CAMP_WATER + 1) for dx in range(-CAMP_WATER, CAMP_WATER + 1)]
        close = [_land_char(seed, x + dx, y + dy) == "~" for dx, dy in ring if max(abs(dx), abs(dy)) <= CAMP_CLEARING]
        wide = (_land_char(seed, x + dx, y + dy) == "~" for dx, dy in ring)
        return not any(close) and any(wide) and _open_country(seed, x, y, 40)
    for reach in range(0, 800, 4):
        for step in range(-reach, reach + 1, 4):
            for x, y in ((step, -reach), (step, reach), (-reach, step), (reach, step)):
                if suits(x, y):
                    return x, y
    return 0, 0


def _camp_ground(cx: int, cy: int) -> dict[str, str]:
    """A playable start: cleared ground, with one of each resource a short walk away."""
    shaped = {f"{x},{y}": "." for y in range(cy - 2, cy + 2) for x in range(cx - 2, cx + 2)}
    for dx, dy, kind in ((-6, -1, "forest"), (5, 0, "rock"), (0, -6, "berries"), (0, 6, "water")):
        shaped[f"{cx + dx},{cy + dy}"] = TILE_CHARS[kind]
    return shaped


def _base_char(world: dict, x: int, y: int) -> str:
    """The land as it was before anyone touched it."""
    return world["shaped"].get(f"{x},{y}") or _land_char(world["seed"], x, y)


def _open_chunk(world: dict, cx: int, cy: int) -> None:
    """First sight of a chunk: only now do its trees, bushes and herds start to exist in the save."""
    key = f"{cx},{cy}"
    if key in world["chunks"]:
        return
    world["chunks"][key] = 1
    stocks, shaped, camp = world["stocks"], world["shaped"], world["camp"]
    land, grazing = _land(world["seed"], cx, cy), []
    for dy, row in enumerate(land):
        for dx, char in enumerate(row):
            x, y = cx * CHUNK + dx, cy * CHUNK + dy
            at = f"{x},{y}"
            char = shaped.get(at, char)
            if char in FULL_STOCK_CHAR:
                stocks[at] = FULL_STOCK_CHAR[char]
            if char in ".T" and dist(x, y, camp[0], camp[1]) >= 8:
                grazing.append((x, y))
    rng = random.Random(f"{world['seed']}:{key}:herds")
    if grazing and rng.random() < HERD_CHANCE:
        x, y = rng.choice(grazing)
        world["herds"].append({"kind": "boar" if rng.random() < 0.4 else "deer", "x": x, "y": y, "count": rng.randint(3, 5)})


def new_world(seed: int, now: float, perks: tuple | list = ()) -> dict[str, Any]:
    cx, cy = CAMP or _find_camp(seed)
    shaped = _camp_ground(cx, cy)
    villagers = []
    for i, base in enumerate(STARTING_VILLAGERS):
        villagers.append({
            "name": base["name"], "trait": base["trait"],
            "x": cx - 1 + i, "y": cy, "energy": MAX_ENERGY, "health": MAX_HEALTH, "hungry": 0,
            "skills": list(base["skills"]), "inv": {"food": 4 if "full_packs" in perks else 2},
            "memory": [], "heard": [], "feedback": [],
            "standing_orders": [], "thought": "",
            "seen": {},  # "x,y" -> 1: fast to test, and JSON friendly
        })
    world: dict[str, Any] = {
        "schema": SCHEMA_VERSION, "seed": seed, "day": 1,
        "born": now, "land_rev": 0,  # the page refetches the land only when this moves
        "camp": [cx, cy],
        "shaped": shaped,  # where the camp differs from what the seed grew
        "changed": dict(shaped),  # "x,y" -> tile, for land that differs now; everything else follows from the seed
        "chunks": {},  # "cx,cy" -> 1 for every chunk that has been opened
        "villagers": villagers, "built": [], "guidance": "", "guidance_day": 0,
        "last_planned_day": 0, "log": [], "day_started_at": now, "away": None,
        "speed": 1, "paused_at": None, "last_read": now,
        "store": {}, "store_at": [cx, cy - 1], "depots": [], "soil": {}, "woodlots": [],
        "fire_out": False,
        "pending_plans": None,  # a council's plans, waiting for the next dawn
        "folk": 0, "folk_stats": None,
        "stocks": {},  # filled in chunk by chunk, as the land is first seen
        "herds": [],
        "dead": [], "emptied": 0, "fallen": None,
        "guide": {"insight": 5 if "old_songs" in perks else 0,
                  "trust": 65 if "first_trust" in perks else START_TRUST,
                  "planted": ["sowing"] if "seed_memory" in perks else [],
                  "known": ["sowing"] if "seed_memory" in perks else [],
                  "upgrades": [], "attempts": {}, "focus": None, "focus_start": None, "era": "Stone Age"},
    }
    if "seed_memory" in perks:
        villagers[0]["skills"].append("farming")
    for v in villagers:
        _reveal(world, v)
    return world


_CHAR_TO_TILE = {c: t for t, c in TILE_CHARS.items()}
FULL_STOCK = {"berries": BUSH_FOOD, "forest": TREE_WOOD}


FULL_STOCK_CHAR = {TILE_CHARS[t]: n for t, n in FULL_STOCK.items()}


def _char(world: dict, x: int, y: int) -> str:
    return world["changed"].get(f"{x},{y}") or _land_char(world["seed"], x, y)


def tile(world: dict, x: int, y: int) -> str:
    return _CHAR_TO_TILE[_char(world, x, y)]


def villager(world: dict, name: str) -> dict | None:
    for v in world["villagers"]:
        if v["name"].lower() == str(name).lower():
            return v
    return None


def season(world: dict) -> str:
    return SEASONS[((world["day"] - 1) // SEASON_DAYS) % len(SEASONS)]


def _near_built(world: dict, x: int, y: int, kinds: tuple[str, ...], reach: int = SHELTER_RANGE) -> bool:
    return any(b["kind"] in kinds and dist(b["x"], b["y"], x, y) <= reach for b in world["built"])


def _near_tile(world: dict, x: int, y: int, kind: str, reach: int) -> bool:
    return any(tile(world, tx, ty) == kind
               for ty in range(y - reach, y + reach + 1) for tx in range(x - reach, x + reach + 1))


def has(world: dict, upgrade: str) -> bool:
    return upgrade in world["guide"]["upgrades"]


def _vision(world: dict) -> int:
    return VISION + (1 if has(world, "keen_eyes") else 0)


def _memory_lines(world: dict) -> int:
    return MEMORY_LINES + (2 if has(world, "long_memory") else 0)


def max_health(world: dict) -> int:
    return MAX_HEALTH + (1 if has(world, "hardy") else 0)


def _knows(world: dict, idea: str) -> bool:
    return idea in world["guide"]["known"]


def _reveal(world: dict, v: dict) -> int:
    if not isinstance(v["seen"], dict):
        v["seen"] = dict.fromkeys(v["seen"], 1)
    seen = v["seen"]
    before = len(seen)
    reach = _vision(world)
    for cy in range((v["y"] - reach) >> 4, ((v["y"] + reach) >> 4) + 1):
        for cx in range((v["x"] - reach) >> 4, ((v["x"] + reach) >> 4) + 1):
            _open_chunk(world, cx, cy)
    for y in range(v["y"] - reach, v["y"] + reach + 1):
        for x in range(v["x"] - reach, v["x"] + reach + 1):
            seen[f"{x},{y}"] = 1
    return len(seen) - before


def find_path(world: dict, v: dict, x: int, y: int) -> list[list[int]] | None:
    """Shortest walk over land this villager has seen. Includes both ends."""
    seen = v["seen"]
    start = (v["x"], v["y"])
    prev: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue = deque([start])
    while queue:
        cx, cy = queue.popleft()
        if (cx, cy) == (x, y):
            path = []
            at: tuple[int, int] | None = (cx, cy)
            while at is not None:
                path.append(list(at))
                at = prev[at]
            return path[::-1]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in prev:
                    continue
                if f"{nx},{ny}" in seen and _char(world, nx, ny) != "~":
                    prev[(nx, ny)] = (cx, cy)
                    queue.append((nx, ny))
    return None


def _bonus(world: dict, key: str) -> int:
    kinds = {b["kind"] for b in world["built"]}
    return sum(int(BUILDINGS[k].get(key, 0)) for k in kinds if k in BUILDINGS)


# ---------------------------------------------------------------- perception

def observe(world: dict, v: dict) -> str:
    """Egocentric text view: only what this villager can see and remembers."""
    reach = _vision(world)
    x0, y0 = v["x"] - reach, v["y"] - reach
    x1, y1 = v["x"] + reach + 1, v["y"] + reach + 1
    rows = []
    stores = {(x, y) for x, y, _ in _stores(world)}
    for y in range(y0, y1):
        row = []
        for x in range(x0, x1):
            if (x, y) == (v["x"], v["y"]):
                row.append("@")
            elif (x, y) in stores:
                row.append("S")
            elif any(h["x"] == x and h["y"] == y for h in world["herds"]):
                row.append("D")
            elif any(b["x"] == x and b["y"] == y for b in world["built"]):
                field = any(b["x"] == x and b["y"] == y and b["kind"] == "field" for b in world["built"])
                row.append("F" if field else "L")
            elif _char(world, x, y) == "b" and world["stocks"].get(f"{x},{y}", 0) <= 0:
                row.append(",")
            else:
                row.append(_char(world, x, y))
        rows.append("".join(row))
    near = [o["name"] for o in world["villagers"]
            if o is not v and dist(o["x"], o["y"], v["x"], v["y"]) <= reach]
    lines = [
        f"## {v['name']} ({v['trait']}) at ({v['x']},{v['y']}) energy {v['energy']}/{MAX_ENERGY}, "
        f"health {v['health']}/{max_health(world)}" + (f", {v['hungry']} hungry nights in a row" if v["hungry"] else ""),
        f"skills: {', '.join(v['skills']) or 'none'}; carrying: {_fmt_inv(v['inv'])}",
        f"view, top-left=({x0},{y0}):", *rows,
    ]
    if near:
        lines.append("can see: " + ", ".join(f"{n}" for n in near))
    herds = [h for h in world["herds"] if dist(h["x"], h["y"], v["x"], v["y"]) <= reach]
    if herds:
        lines.append("animals: " + ", ".join(f"{h['count']} {h['kind']} at ({h['x']},{h['y']})" for h in herds))
    if v["memory"]:
        lines.append("remembers: " + " | ".join(v["memory"][-_memory_lines(world):]))
    if v["heard"]:
        lines.append("heard: " + " | ".join(v["heard"][-HEARD_LINES:]))
    if v["feedback"]:
        lines.append("yesterday went wrong: " + " | ".join(v["feedback"][-3:]))
    if v["standing_orders"]:
        lines.append("habit: " + ", ".join(describe_action(a) for a in v["standing_orders"]))
    for x, y, inv in _stores(world):
        if dist(x, y, v["x"], v["y"]) <= reach:
            lines.append(f"store at ({x},{y}) holds {_fmt_inv(inv)}")
    for idea in world["guide"]["planted"]:
        if idea not in world["guide"]["known"]:
            spec = IDEAS[idea]
            place = {"water": " near water", "fire": " beside a fire pit", None: ""}[spec["near"]]
            lines.append(f"an idea came to you: {spec['hint']} (experiment {idea}{place}, uses {_fmt_inv(spec['try'])})")
    return "\n".join(lines)


def _fmt_inv(inv: dict) -> str:
    items = [f"{n} {k}" for k, n in inv.items() if n]
    return ", ".join(items) or "nothing"


def describe_action(a: dict) -> str:
    verb = a.get("verb")
    if verb == "walk":
        return f"walk to ({a.get('x')},{a.get('y')})"
    if verb == "gather":
        return f"gather {a.get('item')}"
    if verb == "build":
        return f"build {a.get('item')}"
    if verb == "trade":
        return f"trade with {a.get('target')}"
    if verb in ("talk", "teach"):
        extra = a.get("item") if verb == "teach" else repr(str(a.get("text", ""))[:40])
        return f"{verb} {a.get('target')} {extra}"
    return str(verb)


# ---------------------------------------------------------------- validation + execution

def _goods(raw: Any) -> dict[str, int] | None:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return None
    goods = {}
    for k, n in raw.items():
        if k not in ITEMS or not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            return None
        goods[k] = n
    return goods


def _discover(world: dict, v: dict) -> None:
    """Picking bushes bare leaves seeds in the dirt; someone eventually notices them sprout."""
    if world["emptied"] < EMPTIED_FOR_FARMING or any("farming" in o["skills"] for o in world["villagers"]):
        return
    v["skills"].append("farming")
    world.setdefault("_events", []).append(f"{v['name']} noticed seeds sprouting where the bushes were picked bare")


def _room(world: dict, v: dict, item: str) -> int:
    load = sum(n * WEIGHTS.get(k, 1) for k, n in v["inv"].items())
    limit = CARRY_LIMIT + (PACK_FRAME_BONUS if has(world, "pack_frames") else 0)
    return max(0, limit - load) // WEIGHTS.get(item, 1)


def _stores(world: dict) -> list[tuple[int, int, dict]]:
    """The main camp store, plus every depot the village has built."""
    return [(*world["store_at"], world["store"])] + [(d["x"], d["y"], d["inv"]) for d in world["depots"]]


def _packs_near(world: dict, v: dict, reach: int) -> list[dict]:
    """Stores within reach, closest first."""
    close = [(dist(x, y, v["x"], v["y"]), i, inv) for i, (x, y, inv) in enumerate(_stores(world))
             if dist(x, y, v["x"], v["y"]) <= reach]
    return [inv for _, _, inv in sorted(close, key=lambda c: c[:2])]


def _near_store(world: dict, v: dict, reach: int = STORE_REACH) -> bool:
    return bool(_packs_near(world, v, reach))


def _have(world: dict, v: dict, item: str) -> int:
    """What this villager can lay hands on for building: their pack, plus any store close by."""
    return v["inv"].get(item, 0) + sum(p.get(item, 0) for p in _packs_near(world, v, BUILD_REACH))


def _spend(world: dict, v: dict, item: str, n: int) -> None:
    for pack in [v["inv"]] + _packs_near(world, v, BUILD_REACH):
        taken = min(pack.get(item, 0), n)
        pack[item] = pack.get(item, 0) - taken
        n -= taken


def _use_store(world: dict, v: dict, verb: str, act: dict) -> tuple[int, str | None, str]:
    packs = _packs_near(world, v, STORE_REACH)
    if not packs:
        return 1, f"{v['name']} is too far from any store", "too far"
    pack = packs[0]
    item = act.get("item")
    if item not in ITEMS:
        return 1, f"there is no {item!r} to move", "confused"
    want = act.get("n") if isinstance(act.get("n"), int) and act.get("n") > 0 else 10 ** 6
    if verb == "deposit":
        n = min(want, v["inv"].get(item, 0))
        if n <= 0:
            return 1, f"{v['name']} is not carrying {item}", "empty-handed"
        v["inv"][item] -= n
        pack[item] = pack.get(item, 0) + n
        return 1, None, f"stored {n} {item}"
    n = min(want, pack.get(item, 0), _room(world, v, item))
    if n <= 0:
        return 1, f"cannot take {item}: the store has none or the pack is full", "empty-handed"
    pack[item] -= n
    v["inv"][item] = v["inv"].get(item, 0) + n
    return 1, None, f"took {n} {item} from the store"


def _cut_tree(world: dict, x: int, y: int, amount: int) -> int:
    """Cut a forest tile. An emptied tile is bare ground until young trees seed from a neighbour."""
    key = f"{x},{y}"
    amount = min(amount, world["stocks"].get(key, 0))
    world["stocks"][key] = world["stocks"].get(key, 0) - amount
    if world["stocks"][key] <= 0:
        del world["stocks"][key]
        world["changed"][key] = "."
        world.setdefault("_events", []).append(f"The trees at ({x},{y}) are gone")
    return amount


def _gather_wood(world: dict, v: dict, fx: dict) -> tuple[int, str | None, str]:
    room = _room(world, v, "wood")
    if room <= 0:
        return 1, f"{v['name']} cannot carry any more", "overloaded"
    trees = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            tx, ty = v["x"] + dx, v["y"] + dy
            key = f"{tx},{ty}"
            if world["stocks"].get(key, 0) > 0 and (tile(world, tx, ty) == "forest" or key in world["woodlots"]):
                trees.append((world["stocks"][key], tx, ty))
    if not trees:
        return 1, f"no wood within reach of ({v['x']},{v['y']})", "empty-handed"
    _, tx, ty = max(trees)
    amount = min(2 + (1 if _knows(world, "copper") else 0), room)
    if f"{tx},{ty}" in world["woodlots"]:
        amount = min(amount, world["stocks"][f"{tx},{ty}"])
        world["stocks"][f"{tx},{ty}"] -= amount
    else:
        amount = _cut_tree(world, tx, ty, amount)
    v["inv"]["wood"] = v["inv"].get("wood", 0) + amount
    v["energy"] -= 1
    fx["gain"] = {"wood": amount}
    fx["source"] = [tx, ty]
    return 2, None, f"gathered {amount} wood"


def _hunt(world: dict, v: dict, act: dict, slots_left: int, fx: dict) -> tuple[int, str | None, str]:
    kind = act.get("item")
    herd = next((h for h in world["herds"] if h["kind"] == kind and dist(h["x"], h["y"], v["x"], v["y"]) <= HUNT_REACH), None)
    if kind not in ANIMALS or herd is None:
        return 1, f"no {kind} close enough to hunt", "empty-handed"
    if HUNT_SLOTS > slots_left:
        return slots_left, "not enough daylight left to hunt", "unfinished"
    spec = ANIMALS[kind]
    rng = random.Random(f"{world['seed']}:{world['day']}:{v['name']}:hunt:{herd['x']},{herd['y']}")
    v["energy"] -= 1
    fx["source"] = [herd["x"], herd["y"]]
    if rng.random() < spec["gore"]:
        v["health"] = max(1, v["health"] - GORE_DAMAGE)
        v["feedback"].append(f"gored by a {kind}")
    if rng.random() >= spec["odds"]:
        herd["x"], herd["y"] = _herd_step(world, herd, rng, 3)
        return HUNT_SLOTS, None, f"hunted {kind}, but they got away"
    herd["count"] -= 1
    meat = min(MEAT_PER_KILL, _room(world, v, "meat"))
    v["inv"]["meat"] = v["inv"].get("meat", 0) + meat
    fx["gain"] = {"meat": meat}
    if herd["count"] <= 0:
        world["herds"].remove(herd)
        world.setdefault("_events", []).append(f"{v['name']} killed the last of a {kind} herd")
    return HUNT_SLOTS, None, f"brought down a {kind}"


def _herd_step(world: dict, herd: dict, rng: random.Random, reach: int) -> tuple[int, int]:
    x = herd["x"] + rng.randint(-reach, reach)
    y = herd["y"] + rng.randint(-reach, reach)
    return (x, y) if tile(world, x, y) in ("grass", "forest") else (herd["x"], herd["y"])


def _is_food(world: dict, x: int, y: int) -> bool:
    return f"{x},{y}" in world["stocks"] and tile(world, x, y) != "forest" and f"{x},{y}" not in world["woodlots"]


def _food_near(world: dict, v: dict) -> list[tuple[int, int]]:
    return [(v["x"] + dx, v["y"] + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            if _is_food(world, v["x"] + dx, v["y"] + dy)]


def _ready_food(world: dict, v: dict) -> list[tuple[int, int, int]]:
    winter = season(world) == "winter"
    return [(world["stocks"][f"{x},{y}"], x, y) for x, y in _food_near(world, v)
            if world["stocks"][f"{x},{y}"] > 0 and not (winter and tile(world, x, y) == "berries")]


def _gather_food(world: dict, v: dict, fx: dict) -> tuple[int, str | None, str]:
    near = _food_near(world, v)
    if not near:
        return 1, f"no food within reach of ({v['x']},{v['y']})", "empty-handed"
    winter = season(world) == "winter"
    ready = _ready_food(world, v)
    if not ready:
        if winter:
            return 1, "the bushes are bare for the winter", "empty-handed"
        return 1, "everything within reach has been picked bare", "empty-handed"
    stock, tx, ty = max(ready)
    wild = tile(world, tx, ty) == "berries"
    item = "food" if wild else "grain"
    amount = min(stock, (3 if "foraging" in v["skills"] and wild else 2) + _bonus(world, "food"), _room(world, v, item))
    if amount <= 0:
        return 1, f"{v['name']} cannot carry any more", "overloaded"
    world["stocks"][f"{tx},{ty}"] = stock - amount
    if stock == amount and wild:
        world["emptied"] += 1
        _discover(world, v)
    if not wild:
        key = f"{tx},{ty}"
        world["soil"][key] = max(0.3, world["soil"].get(key, 1.0) - SOIL_LOSS)
    v["inv"][item] = v["inv"].get(item, 0) + amount
    v["energy"] -= 1
    fx["gain"] = {item: amount}
    fx["source"] = [tx, ty]
    return 2, None, f"gathered {amount} {item}"


def _experiment_block(world: dict, v: dict, idea: Any) -> str | None:
    spec = IDEAS.get(idea) if isinstance(idea, str) else None
    guide = world["guide"]
    if spec is None or idea not in guide["planted"]:
        return f"nobody has had the idea {idea!r}"
    if idea in guide["known"]:
        return f"the village already knows {spec['name'].lower()}"
    if spec["near"] == "water" and not _near_tile(world, v["x"], v["y"], "water", FIELD_WATER_RANGE):
        return f"{spec['name'].lower()} has to be tried near water"
    if spec["near"] == "fire" and not _near_built(world, v["x"], v["y"], ("fire_pit",), 2):
        return f"{spec['name'].lower()} has to be tried beside a fire pit"
    missing = {k: n - _have(world, v, k) for k, n in spec["try"].items() if _have(world, v, k) < n}
    if missing:
        return f"needs {_fmt_inv(missing)} more to try {spec['name'].lower()}"
    return None


def _experiment(world: dict, v: dict, idea: str, fx: dict) -> tuple[None, str]:
    """A real attempt: it uses up materials and can fail, though each failure teaches
    something, so the odds improve."""
    spec, guide = IDEAS[idea], world["guide"]
    for k, n in spec["try"].items():
        _spend(world, v, k, n)
    v["energy"] -= 1
    tries = guide["attempts"].get(idea, 0)
    guide["attempts"][idea] = tries + 1
    rng = random.Random(f"{world['seed']}:{world['day']}:{v['name']}:{idea}:{tries}")
    chance = 0.4 + 0.15 * tries + (0.1 if guide["trust"] >= TRUST_EAGER else 0)
    fx["experiment"] = idea
    if rng.random() >= chance:
        fx["worked"] = False
        v["memory"] = (v["memory"] + [f"day {world['day']}: my {spec['name'].lower()} attempt failed"])[-_memory_lines(world):]
        return None, f"tried {spec['name'].lower()}, but it failed"
    fx["worked"] = True
    guide["known"].append(idea)
    guide["insight"] += 4
    if spec["skill"] and spec["skill"] not in v["skills"]:
        v["skills"].append(spec["skill"])
    world.setdefault("_events", []).append(f"{v['name']} worked out {spec['name'].lower()}")
    return None, f"worked out {spec['name'].lower()}"


def execute(world: dict, v: dict, act: Any, slots_left: int,
            fx: dict | None = None) -> tuple[int, str | None, str]:
    """Validate and apply one action. Returns (slots_used, error_or_None, summary).
    ``fx`` collects what the page needs to show it: path, gain, built, target."""
    fx = {} if fx is None else fx
    if not isinstance(act, dict):
        return 1, "that was not an action", "confused"
    verb = act.get("verb")
    if verb not in VERBS:
        return 1, f"there is no action called {verb!r}", "confused"
    if verb != "rest" and v["energy"] <= 0:
        return 1, "too tired to do anything but rest", "slumped"

    if verb == "rest":
        v["energy"] = min(MAX_ENERGY, v["energy"] + 3)
        return 1, None, "rested"

    if verb == "look":
        v["energy"] -= 1
        new = _reveal(world, v)
        return 1, None, f"looked around ({new} new tiles)"

    if verb == "walk":
        x, y = act.get("x"), act.get("y")
        if not (isinstance(x, int) and isinstance(y, int)):
            return 1, "walk needs a place on the map (x,y)", "confused"
        if f"{x},{y}" not in v["seen"]:
            return 1, f"{v['name']} has never seen ({x},{y}) and cannot head there", "lost"
        if tile(world, x, y) == "water":
            return 1, f"({x},{y}) is water; stand beside it instead", "wet feet"
        path = find_path(world, v, x, y)
        if path is None:
            return 1, f"{v['name']} knows no way to reach ({x},{y})", "lost"
        short = len(path) - 1 > slots_left * WALK_PER_SLOT
        if short:  # a long trek: go as far as daylight allows and carry on tomorrow
            path = path[:slots_left * WALK_PER_SLOT + 1]
        cost = max(1, -(-(len(path) - 1) // WALK_PER_SLOT))
        fx["path"] = path
        v["x"], v["y"] = path[-1]
        v["energy"] -= 1
        new = _reveal(world, v)
        where = f"walked toward ({x},{y}), and stopped at ({v['x']},{v['y']}) for the night" if short else f"walked to ({x},{y})"
        return cost, None, where + (f", saw {new} new tiles" if new else "")

    if verb in ("deposit", "take"):
        return _use_store(world, v, verb, act)

    if verb == "hunt":
        return _hunt(world, v, act, slots_left, fx)

    if verb == "gather":
        item = act.get("item")
        if item not in ITEMS:
            return 1, f"cannot gather {item!r}; try wood, stone, food or water", "confused"
        if item == "food":
            return _gather_food(world, v, fx)
        if item in ("grain", "meat"):
            return 1, f"{item} comes from fields and hunting; gather food at a field, or hunt", "confused"
        if item == "wood":
            return _gather_wood(world, v, fx)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                tx, ty = v["x"] + dx, v["y"] + dy
                if YIELD.get(tile(world, tx, ty)) == item:
                    amount = min(3 if _knows(world, "copper") and item == "stone" else 2, _room(world, v, item))
                    if amount <= 0:
                        return 1, f"{v['name']} cannot carry any more", "overloaded"
                    v["inv"][item] = v["inv"].get(item, 0) + amount
                    v["energy"] -= 1
                    fx["gain"] = {item: amount}
                    fx["source"] = [tx, ty]
                    return 2, None, f"gathered {amount} {item}"
        return 1, f"no {item} within reach of ({v['x']},{v['y']})", "empty-handed"

    if verb == "build":
        name = act.get("item")
        spec = BUILDINGS.get(name)
        if spec is None:
            return 1, f"nobody knows how to build {name!r} (known: {', '.join(BUILDINGS)})", "confused"
        if spec.get("idea") and not _knows(world, spec["idea"]):
            return 1, f"nobody has worked out {IDEAS[spec['idea']]['name'].lower()} yet", "unsure"
        if spec["skill"] and spec["skill"] not in v["skills"]:
            return 1, f"{v['name']} does not know {spec['skill']}", "unsure"
        if tile(world, v["x"], v["y"]) != "grass" or any(b["x"] == v["x"] and b["y"] == v["y"] for b in world["built"]):
            return 1, "needs open grass to build on", "blocked"
        if spec.get("near_water") and not _near_tile(world, v["x"], v["y"], "water", spec["near_water"]):
            return 1, f"a {name} must be within {spec['near_water']} tiles of water", "too dry"
        if any((x, y) == (v["x"], v["y"]) for x, y, _ in _stores(world)):
            return 1, "that spot already holds a store", "blocked"
        missing = {k: n - _have(world, v, k) for k, n in spec["cost"].items() if _have(world, v, k) < n}
        if missing:
            return 1, f"needs {_fmt_inv(missing)} more to build {name}", "short of materials"
        if sum(1 for b in world["built"] if b["kind"] == name) >= spec["max"]:
            return 1, f"the camp already has enough of {name}", "redundant"
        if spec["slots"] > slots_left:
            return slots_left, f"not enough daylight left to build {name}", "unfinished"
        for k, n in spec["cost"].items():
            _spend(world, v, k, n)
        built = {"kind": name, "x": v["x"], "y": v["y"], "by": v["name"], "day": world["day"]}
        world["built"].append(built)
        if name in ("field", "woodlot"):
            world["stocks"][f"{v['x']},{v['y']}"] = 0
        if name == "woodlot":
            world["woodlots"].append(f"{v['x']},{v['y']}")
        if name == "depot":
            world["depots"].append({"x": v["x"], "y": v["y"], "inv": {}})
        fx["built"] = built
        v["energy"] -= 1
        return spec["slots"], None, f"built a {name}"

    if verb == "experiment":
        idea = act.get("item")
        block = _experiment_block(world, v, idea)
        if block:
            return 1, block, "puzzled"
        if EXPERIMENT_SLOTS > slots_left:
            return slots_left, "not enough daylight left to try that", "unfinished"
        return EXPERIMENT_SLOTS, *_experiment(world, v, idea, fx)

    # social verbs
    other = villager(world, act.get("target", ""))
    if other is None or other is v:
        return 1, f"there is nobody called {act.get('target')!r} to {verb}", "talking to air"
    if dist(v["x"], v["y"], other["x"], other["y"]) > TALK_RANGE:
        return 1, f"{other['name']} is too far away to {verb}", "shouted into the wind"
    fx["target"] = other["name"]
    v["energy"] -= 1
    if verb == "talk":
        text = str(act.get("text", "")).strip()[:80]
        if not text:
            return 1, "had nothing to say", "silent"
        other["heard"] = (other["heard"] + [f"{v['name']}: {text}"])[-HEARD_LINES:]
        fx["say"] = text
        return 1, None, f"told {other['name']} \"{text}\""
    if verb == "trade":
        give, get = _goods(act.get("give")), _goods(act.get("get"))
        if give is None or get is None or not (give or get):
            return 1, "a trade needs goods, for example give wood 2, get food 2", "confused"
        if any(v["inv"].get(k, 0) < n for k, n in give.items()):
            return 1, f"{v['name']} lacks the goods to give", "empty-handed"
        if any(other["inv"].get(k, 0) < n for k, n in get.items()):
            return 1, f"{other['name']} lacks the goods to give back", "empty-handed"
        for k, n in give.items():
            v["inv"][k] -= n
            other["inv"][k] = other["inv"].get(k, 0) + n
        for k, n in get.items():
            other["inv"][k] -= n
            v["inv"][k] = v["inv"].get(k, 0) + n
        return 1, None, f"traded with {other['name']}"
    # teach
    skill = act.get("item")
    if skill not in v["skills"]:
        return 1, f"{v['name']} cannot teach {skill!r}", "unsure"
    if skill in other["skills"]:
        return 1, f"{other['name']} already knows {skill}", "redundant"
    other["skills"].append(skill)
    return (1 if has(world, "patient_teaching") else 2), None, f"taught {other['name']} {skill}"


def _search(world: dict, v: dict, hit, start: tuple[int, int] | None = None, adjacent: bool = True) -> tuple[int, int] | None:
    """Walk outward over land this villager knows and return the first tile that is on
    (or, with ``adjacent``, beside) something ``hit`` accepts. One search does the work
    of many path calls, which is what keeps a big map fast."""
    seen = v["seen"]
    origin = start or (v["x"], v["y"])
    done = {origin}
    queue = deque([(origin[0], origin[1], 0)])
    around = [(dx, dy) for dy in (0, -1, 1) for dx in (0, -1, 1)]
    while queue:
        x, y, steps = queue.popleft()
        for dx, dy in around if adjacent else ((0, 0),):
            if hit(x + dx, y + dy):
                return x, y
        if steps >= SEARCH_REACH:
            continue
        for dx, dy in around:
            nx, ny = x + dx, y + dy
            if (nx, ny) not in done and f"{nx},{ny}" in seen and _char(world, nx, ny) != "~":
                done.add((nx, ny))
                queue.append((nx, ny, steps + 1))
    return None


def _beside(world: dict, v: dict, x: int, y: int) -> tuple[int, int] | None:
    """The closest reachable land tile on or next to (x,y)."""
    return _search(world, v, lambda a, b: a == x and b == y)


def _nearest_resource(world: dict, v: dict, kind: str) -> tuple[int, int] | None:
    """A reachable land tile on or beside the closest known ``kind`` tile."""
    seen, char = v["seen"], TILE_CHARS[kind]
    return _search(world, v, lambda x, y: f"{x},{y}" in seen and _char(world, x, y) == char)


def _nearest_food(world: dict, v: dict) -> tuple[int, int] | None:
    """The closest known food that can actually be picked today."""
    winter = season(world) == "winter"
    seen, stocks = v["seen"], world["stocks"]

    def ready(x: int, y: int) -> bool:
        key = f"{x},{y}"
        return key in seen and stocks.get(key, 0) > 0 and _is_food(world, x, y) \
            and not (winter and tile(world, x, y) == "berries")
    return _search(world, v, ready)


def _home(world: dict, v: dict) -> tuple[int, int] | None:
    """Beside the closest fire or shelter, for the walk back before dark."""
    homes = sorted((dist(v["x"], v["y"], b["x"], b["y"]), b["x"], b["y"]) for b in world["built"]
                   if b["kind"] in ("fire_pit", "lean_to", "hut"))
    if not homes:  # no shelter yet: the nearest store is home
        homes = sorted((dist(v["x"], v["y"], x, y), x, y) for x, y, _ in _stores(world))
    if homes[0][0] <= 2:
        return (v["x"], v["y"])
    # too far to get back tonight: sleep where you are, unless winter is coming and the walk is worth days
    if homes[0][0] > HOME_REACH and (season(world) not in ("autumn", "winter") or homes[0][0] > SEARCH_REACH):
        return (v["x"], v["y"])
    return _beside(world, v, homes[0][1], homes[0][2])


def _open_ground(world: dict, v: dict) -> tuple[int, int] | None:
    """The closest free grass this villager knows."""
    taken = {(b["x"], b["y"]) for b in world["built"]} | {(x, y) for x, y, _ in _stores(world)}
    return _search(world, v, lambda x, y: (x, y) not in taken and tile(world, x, y) == "grass" and f"{x},{y}" in v["seen"],
                   adjacent=False)


def _gather_trip(world: dict, v: dict, item: str, kind: str) -> list[dict]:
    spot = _nearest_resource(world, v, kind)
    return [{"verb": "walk", "x": spot[0], "y": spot[1]}, {"verb": "gather", "item": item},
            {"verb": "gather", "item": item}] if spot else []


def _focus_shelter(world: dict, v: dict) -> list[dict]:
    hut = BUILDINGS["hut"]
    if sum(1 for b in world["built"] if b["kind"] == "hut") >= hut["max"]:
        return []
    near_camp = _near_store(world, v, BUILD_REACH)
    stored = {k: _have(world, v, k) for k in hut["cost"]}
    if all(stored[k] >= n for k, n in hut["cost"].items()):
        spot = _open_ground(world, v)
        if spot:
            return ([] if near_camp else [{"verb": "walk", "x": spot[0], "y": spot[1]}]) + \
                [{"verb": "walk", "x": spot[0], "y": spot[1]}, {"verb": "build", "item": "hut"}]
        return []
    if stored["wood"] < hut["cost"]["wood"]:
        return _gather_trip(world, v, "wood", "forest")
    return _gather_trip(world, v, "stone", "rock")


def _focus_learn(world: dict, v: dict) -> list[dict]:
    """The steps to try the first planted idea this villager can: fetch what it uses up, from the
    store if it is there, go where it has to be tried, and try it."""
    kinds = {"wood": "forest", "stone": "rock"}
    sx, sy = world["store_at"]
    for idea in world["guide"]["planted"]:
        if idea in world["guide"]["known"]:
            continue
        spec = IDEAS[idea]
        fetch: list[dict] = []
        stuck = False
        for item, n in spec["try"].items():
            lacking = n - v["inv"].get(item, 0)
            if lacking <= 0:
                continue
            if sum(world["store"].get(k, 0) for k in (EDIBLE if item == "food" else (item,))) >= lacking:
                held = next(k for k in (EDIBLE if item == "food" else (item,)) if world["store"].get(k, 0) >= 1)
                if item == "food" and held != "food":
                    stuck = True  # an experiment with food wants food itself, not grain or meat
                    break
                fetch.append({"verb": "take", "item": item, "n": lacking})
            elif item in kinds:
                trip = _gather_trip(world, v, item, kinds[item])
                if trip:
                    return trip
                stuck = True
                break
            else:
                stuck = True
                break
        if stuck:
            continue
        steps: list[dict] = []
        if fetch:
            if not _near_store(world, v):
                spot = _beside(world, v, sx, sy)
                if not spot:
                    continue
                steps.append({"verb": "walk", "x": spot[0], "y": spot[1]})
            steps += fetch
        place = None
        if spec["near"] == "water":
            place = None if not fetch and _near_tile(world, v["x"], v["y"], "water", FIELD_WATER_RANGE) else _nearest_resource(world, v, "water")
        elif spec["near"] == "fire":
            fires = [b for b in world["built"] if b["kind"] == "fire_pit"]
            if not fires:
                continue
            if fetch or dist(fires[0]["x"], fires[0]["y"], v["x"], v["y"]) > 2:
                place = _beside(world, v, fires[0]["x"], fires[0]["y"])
        walk = [{"verb": "walk", "x": place[0], "y": place[1]}] if place else []
        return (steps + walk + [{"verb": "experiment", "item": idea}])[:MAX_ACTIONS]
    return []


def _edible(inv: dict) -> int:
    return sum(inv.get(k, 0) for k in EDIBLE)


def _deliver(world: dict, v: dict, items: tuple[str, ...]) -> list[dict]:
    """Walk to the closest store and put things away, so everyone can use them."""
    x, y, _ = min(_stores(world), key=lambda s: dist(s[0], s[1], v["x"], v["y"]))
    if _near_store(world, v):
        return [{"verb": "deposit", "item": i} for i in items]
    spot = _beside(world, v, x, y)
    return [{"verb": "walk", "x": spot[0], "y": spot[1]}] + [{"verb": "deposit", "item": i} for i in items] if spot else []


def _nearest_herd(world: dict, v: dict) -> dict | None:
    herds = [h for h in world["herds"] if dist(h["x"], h["y"], v["x"], v["y"]) <= VISION + 2]
    return min(herds, key=lambda h: dist(h["x"], h["y"], v["x"], v["y"])) if herds else None


def _scout(world: dict, v: dict) -> list[dict]:
    """Head for the edge of what this villager knows, keeping one direction for a season
    so they cover ground instead of pacing about the camp."""
    angle = random.Random(f"{world['seed']}:{v['name']}:{(world['day'] - 1) // SEASON_DAYS}").random() * math.tau
    hx, hy = math.cos(angle), math.sin(angle)
    seen, best = v["seen"], (None, -math.inf)

    def weigh(x: int, y: int) -> bool:
        nonlocal best
        if f"{x + 1},{y}" not in seen or f"{x - 1},{y}" not in seen or f"{x},{y + 1}" not in seen or f"{x},{y - 1}" not in seen:
            score = (x - v["x"]) * hx + (y - v["y"]) * hy
            if score > best[1]:
                best = ((x, y), score)
        return False
    _search(world, v, weigh, adjacent=False)
    return [{"verb": "walk", "x": best[0][0], "y": best[0][1]}, {"verb": "look"}] if best[0] else []


def instinct_actions(world: dict, v: dict) -> list[dict]:
    """What a villager does unprompted, for free: eat, fetch wood, raise the first
    shelter, keep the store and fire going, hunt what they can see, otherwise wander
    the edge of what they know. Skills, coordination and choices between buildings
    wait for a council."""
    now = season(world)
    home = _home(world, v)
    go_home = [{"verb": "walk", "x": home[0], "y": home[1]}] if home and home != (v["x"], v["y"]) else []
    if v["energy"] <= 2:
        return go_home + [{"verb": "rest"}, {"verb": "rest"}]
    # Nomads shelter where they are: a band that has moved on raises a new lean-to.
    sheltered = _near_built(world, v["x"], v["y"], ("lean_to", "hut", "stone_house"), HOME_REACH)
    if not sheltered and v["inv"].get("wood", 0) >= BUILDINGS["lean_to"]["cost"]["wood"]:
        spot = _open_ground(world, v)
        if spot:
            return [{"verb": "walk", "x": spot[0], "y": spot[1]}, {"verb": "build", "item": "lean_to"}]
    focus = world["guide"]["focus"] if world["guide"]["trust"] >= TRUST_HEEDED else None
    people = len(world["villagers"])
    own = _edible(v["inv"])
    nearby = _packs_near(world, v, HOME_REACH)
    stored = sum(_edible(p) for p in nearby)
    wood_stored = sum(p.get("wood", 0) for p in nearby)
    has_fire = _near_built(world, v["x"], v["y"], ("fire_pit",), HOME_REACH)
    acts: list[dict] = []
    if not _near_tile(world, v["x"], v["y"], "water", WATER_RANGE) and v["inv"].get("water", 0) < 1:
        acts = _gather_trip(world, v, "water", "water")
    if not acts and own < 2 and stored > 0:
        item = next(k for k in EDIBLE if any(p.get(k, 0) > 0 for p in nearby))
        x, y, _ = min((s for s in _stores(world) if s[2].get(item, 0) > 0), key=lambda s: dist(s[0], s[1], v["x"], v["y"]))
        spot = _beside(world, v, x, y)
        if spot:
            acts = [{"verb": "walk", "x": spot[0], "y": spot[1]}, {"verb": "take", "item": item, "n": 3}]
    enough = 3 + ({"food": 3, "explore": -1}.get(focus, 0))
    stocking = now in ("summer", "autumn") and stored < 4 * people
    if not acts and (own < enough or stocking):
        herd = _nearest_herd(world, v)
        spot = _nearest_food(world, v)
        if herd is not None and (spot is None or own < 2):
            near = _beside(world, v, herd["x"], herd["y"])
            if near:
                acts = [{"verb": "walk", "x": near[0], "y": near[1]}, {"verb": "hunt", "item": herd["kind"]}]
        if not acts and spot:
            acts = [{"verb": "walk", "x": spot[0], "y": spot[1]}, {"verb": "gather", "item": "food"},
                    {"verb": "gather", "item": "food"}]
        if acts and stocking and own >= 2:
            acts += _deliver(world, v, ("grain", "food", "meat"))
        if not acts and own < 2 and stored <= 0 and now != "winter":  # picked bare: move on, as bands did before farming
            acts = _scout(world, v)
            if acts:
                return acts
    if not acts and has_fire and wood_stored < 3 and now != "winter":
        acts = _gather_trip(world, v, "wood", "forest")
        if acts:
            acts += _deliver(world, v, ("wood",))
    if not acts and not sheltered:
        acts = _gather_trip(world, v, "wood", "forest")
    if not acts and focus == "shelter" and sheltered:
        acts = _focus_shelter(world, v)
        if acts and acts[-1].get("verb") == "gather":
            acts += _deliver(world, v, ("wood", "stone"))
    if not acts and focus == "learn":
        acts = _focus_learn(world, v)
    if not acts and now in ("autumn", "winter"):  # bands range in the warm months and winter where they can
        return go_home + [{"verb": "rest"}]
    if not acts:
        acts = _scout(world, v)
    return (acts or [{"verb": "rest"}]) + go_home


def _pose(v: dict) -> dict:
    return {"x": v["x"], "y": v["y"], "energy": v["energy"], "inv": dict(v["inv"])}


def _nothing_to_do(world: dict, v: dict, act: dict) -> bool:
    verb, item = act.get("verb"), act.get("item")
    if verb == "deposit":
        return v["inv"].get(item, 0) <= 0 or not _near_store(world, v)
    if verb == "take":
        packs = _packs_near(world, v, STORE_REACH)
        return not packs or packs[0].get(item, 0) <= 0 or _room(world, v, item) <= 0
    if verb == "gather":
        return _room(world, v, item) <= 0 if item in ITEMS else False
    if verb == "hunt":
        return not any(h["kind"] == item and dist(h["x"], h["y"], v["x"], v["y"]) <= HUNT_REACH for h in world["herds"])
    return False


def _can_build(world: dict, v: dict, act: dict) -> bool:
    spec = BUILDINGS.get(act.get("item"))
    return bool(spec) and all(_have(world, v, k) >= n for k, n in spec["cost"].items()) and \
        sum(1 for b in world["built"] if b["kind"] == act.get("item")) < spec["max"] and \
        (not spec["skill"] or spec["skill"] in v["skills"]) and \
        (not spec.get("idea") or _knows(world, spec["idea"]))


def _eat(world: dict, v: dict) -> bool:
    for pack in [v["inv"]] + _packs_near(world, v, SHELTER_RANGE):
        for item in EDIBLE:
            if pack.get(item, 0) > 0:
                pack[item] -= 1
                return True
    return False


def _drink(world: dict, v: dict) -> bool:
    if _near_tile(world, v["x"], v["y"], "water", WATER_RANGE):
        return True
    for pack in [v["inv"]] + _packs_near(world, v, SHELTER_RANGE):
        if pack.get("water", 0) > 0:
            pack["water"] -= 1
            return True
    return False


def _rot(pack: dict) -> int:
    lost = 0
    for item, share in ROT_BY_ITEM.items():
        spoiled = pack.get(item, 0) // share
        if spoiled:
            pack[item] -= spoiled
            lost += spoiled
    return lost


def _lit_fire_near(world: dict, x: int, y: int) -> bool:
    return any(b["kind"] == "fire_pit" and b.get("lit", True) and dist(b["x"], b["y"], x, y) <= SHELTER_RANGE
               for b in world["built"])


def _night(world: dict, v: dict, entry: dict) -> str | None:
    """Eat, drink, rot, cold and wolves. Returns the cause if this night's damage was fatal."""
    ate = _eat(world, v)
    v["hungry"] = 0 if ate else v["hungry"] + 1
    if not ate:
        v["feedback"].append("went to sleep hungry")
    drank = _drink(world, v)
    v["dry"] = 0 if drank else v.get("dry", 0) + 1
    if not drank:
        v["feedback"].append("went to sleep thirsty")
    parched = v["dry"] >= 2  # a dry night is miserable; two in a row start to do damage
    stored = any(b["kind"] == "drying_rack" for b in world["built"]) or _near_built(world, v["x"], v["y"], ("storehouse",))
    rot = 0 if stored else _rot(v["inv"])
    if rot:
        v["feedback"].append(f"{rot} food rotted overnight")
    x, y = v["x"], v["y"]
    warm = _near_built(world, x, y, ("lean_to", "hut", "stone_house")) or _lit_fire_near(world, x, y)
    cold = season(world) == "winter" and not warm
    rng = random.Random(f"{world['seed']}:{world['day']}:{v['name']}:night")
    exposed = 0.4 if _near_built(world, x, y, ("lean_to", "hut", "stone_house")) else 1.0
    bitten = not _lit_fire_near(world, x, y) and rng.random() < WOLF_CHANCE * exposed
    harm = (0 if ate else 1) + (1 if parched else 0) + (1 if cold else 0) + (WOLF_BITE if bitten else 0)
    if cold:
        v["feedback"].append("nearly froze in the open")
    if bitten:
        v["feedback"].append("wolves attacked in the night")
    v["health"] = min(max_health(world), v["health"] + (1 if harm == 0 else -harm))
    recovery = (OVERNIGHT_ENERGY if ate else HUNGRY_ENERGY) + _bonus(world, "rest")
    v["energy"] = min(MAX_ENERGY, max(0, v["energy"]) + recovery)
    entry["night"] = {"ate": ate, "drank": drank, "cold": cold, "bitten": bitten, "health": v["health"], **_pose(v)}
    if v["health"] > 0:
        return None
    return "wolves" if bitten else ("the cold" if cold else ("thirst" if parched else "hunger"))


def _burn_fuel(world: dict, events: list[str]) -> None:
    """A fire eats wood from a store beside it every night. With none it goes out, and warmth and safety go too."""
    fires = [b for b in world["built"] if b["kind"] == "fire_pit"]
    for fire in fires:
        pack = next((inv for x, y, inv in _stores(world)
                     if dist(x, y, fire["x"], fire["y"]) <= FIRE_FUEL_REACH and inv.get("wood", 0) > 0), None)
        if pack:
            pack["wood"] -= 1
            if not fire.get("lit", True):
                events.append("The fire is lit again")
            fire["lit"] = True
        else:
            if fire.get("lit", True):
                events.append("The fire went out: no wood in the store")
            fire["lit"] = False
    world["fire_out"] = any(not b.get("lit", True) for b in fires)


def _beds(world: dict) -> int:
    extra = sum({"hut": 2, "stone_house": 3}.get(b["kind"], 0) for b in world["built"])
    return min(MAX_VILLAGERS, 3 + extra)


def _arrival(world: dict, events: list[str]) -> None:
    """A wanderer joins when there is a spare bed and the camp is eating well."""
    alive = world["villagers"]
    if not alive or len(alive) >= _beds(world) or sum(_edible(v["inv"]) for v in alive) + sum(_edible(inv) for _, _, inv in _stores(world)) < 2 * len(alive):
        return
    rng = random.Random(f"{world['seed']}:{world['day']}:arrival")
    taken = {v["name"] for v in alive} | {d["name"] for d in world["dead"]}
    names = [n for n in WANDERERS if n not in taken]
    folk = world.get("folk", 0)
    if not names or rng.random() > (0.5 if folk else 0.25):
        return
    if folk:
        world["folk"] = folk - 1
    camp = next((b for b in world["built"] if b["kind"] in ("hut", "stone_house")), alive[0])
    v = {"name": names[0], "trait": rng.choice(("quiet and watchful", "cheerful and reckless", "stubborn, proud of their work",
                                                "kind, always sharing food")),
         "x": camp["x"], "y": camp["y"], "energy": MAX_ENERGY, "health": MAX_HEALTH, "hungry": 0,
         "skills": [rng.choice(SKILLS[:3])], "inv": {"food": 2}, "memory": [], "heard": [], "feedback": [],
         "standing_orders": [], "thought": "", "seen": {}}
    _reveal(world, v)
    alive.append(v)
    events.append(f"{v['name']} stepped up from among the folk" if folk else f"{v['name']} wandered in looking for a home")


def _herds_live(world: dict) -> None:
    rng = random.Random(f"{world['seed']}:{world['day']}:herds")
    spring = season(world) == "spring" and (world["day"] - 1) % SEASON_DAYS == 0
    for herd in world["herds"]:
        herd["x"], herd["y"] = _herd_step(world, herd, rng, 2)
        if spring and 2 <= herd["count"] < HERD_LIMIT:
            herd["count"] += 1


def _seed_forest(world: dict) -> None:
    """Each year, cleared land beside living forest may take young trees. It is slow, and it needs a neighbour."""
    rng = random.Random(f"{world['seed']}:{world['day']}:seeds")
    taken = {(b["x"], b["y"]) for b in world["built"]}
    for key, char in sorted(world["changed"].items()):
        x, y = map(int, key.split(","))
        if char != "." or _base_char(world, x, y) != "T" or (x, y) in taken:
            continue
        beside = any(_char(world, x + dx, y + dy) == "T" for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
        if beside and rng.random() < SEEDING_CHANCE:
            world["changed"][key] = "T"
            world["stocks"][key] = 1


def _grow(world: dict) -> None:
    _herds_live(world)
    if season(world) == "winter":
        return
    if season(world) == "spring" and (world["day"] - 1) % SEASON_DAYS == 0:
        _seed_forest(world)
    for key, stock in list(world["stocks"].items()):
        x, y = map(int, key.split(","))
        kind = tile(world, x, y)
        if key in world["woodlots"]:
            if world["day"] % WOODLOT_GROW_DAYS == 0:
                world["stocks"][key] = min(TREE_WOOD, stock + 1)
        elif kind == "forest":
            if world["day"] % TREE_REGROW_DAYS == 0:
                world["stocks"][key] = min(TREE_WOOD, stock + 1)
        elif kind == "berries":
            if world["day"] % BUSH_REGROW_DAYS == 0:
                world["stocks"][key] = min(BUSH_FOOD, stock + 1)
        else:
            soil = world["soil"].get(key, 1.0)
            world["stocks"][key] = min(round(FIELD_FOOD * soil), stock + max(1, round(FIELD_GROWTH * soil)))
            world["soil"][key] = min(1.0, soil + SOIL_REST)


def era(world: dict) -> str:
    reached = max((ERAS.index(IDEAS[i]["era"]) for i in world["guide"]["known"] if i in IDEAS), default=0)
    if reached == 0 and "sowing" in world["guide"]["known"]:
        reached = 1  # sowing is a Stone Age idea, and it is what begins the Farming Age
    return ERAS[reached]


def boost(world: dict, what: str) -> float:
    """Everything the village has worked out that multiplies ``what``. Ranges add instead."""
    total = 0.0 if what in ("water_range", "fish") else 1.0
    for idea in world["guide"]["known"]:
        n = IDEAS.get(idea, {}).get("boost", {}).get(what)
        if n:
            total = total + n if what in ("water_range", "fish") else total * n
    return total


def population(world: dict) -> int:
    return len(world["villagers"]) + world.get("folk", 0)


def housing(world: dict) -> int:
    """How many of the folk the village's homes can hold."""
    return int(sum(FOLK_HOMES.get(b["kind"], 0) for b in world["built"]) * boost(world, "housing"))


def _folk_reach(world: dict) -> int:
    return min(60, int((FOLK_REACH + math.sqrt(world.get("folk", 0)) / 2) * boost(world, "reach")))


def _rings(cx: int, cy: int, reach: int):
    """Tiles around a point, nearest first."""
    yield cx, cy
    for r in range(1, reach + 1):
        for x in range(cx - r, cx + r + 1):
            yield x, cy - r
            yield x, cy + r
        for y in range(cy - r + 1, cy + r):
            yield cx - r, y
            yield cx + r, y


def _folk_site(world: dict, name: str, reach: int) -> tuple[int, int] | None:
    """The nearest open grass to the store for the folk to build on. Fields need water close by."""
    taken = {(b["x"], b["y"]) for b in world["built"]} | {(x, y) for x, y, _ in _stores(world)}
    cx, cy = world["store_at"]
    wet = BUILDINGS[name].get("near_water")
    if wet:
        wet += int(boost(world, "water_range"))
    for x, y in _rings(cx, cy, reach):
        if (x, y) in taken or tile(world, x, y) != "grass":
            continue
        if wet and not _near_tile(world, x, y, "water", wet):
            continue
        return x, y
    return None


def _folk_build(world: dict, stats: dict, reach: int) -> None:
    """What the folk raise by themselves: homes when they are crowded, fields when food runs short."""
    store, folk = world["store"], world["folk"]
    count = Counter(b["kind"] for b in world["built"])
    crowded = folk + 2 + folk // 8 > housing(world) or (folk == 0 and housing(world) == 0 and len(world["villagers"]) >= 3)
    wants: list[str] = []
    if crowded:
        wants.append("stone_house" if _knows(world, "masonry") and store.get("stone", 0) >= 6 else "hut")
    grown = count["field"] * FIELD_GROWTH * boost(world, "food")
    if _knows(world, "sowing") and grown < folk * 1.3 + 2:
        wants.append("field")
    if _knows(world, "coppicing") and count["woodlot"] < 2 + folk // 15:
        wants.append("woodlot")
    if count["fire_pit"] < 1 + folk // 40:
        wants.append("fire_pit")
    if _knows(world, "pottery") and not count["storehouse"]:
        wants.append("storehouse")
    for _ in range(1 + folk // 6):
        done = False
        for name in wants:
            spec = BUILDINGS[name]
            if count[name] >= spec["max"] or any(store.get(k, 0) < n for k, n in spec["cost"].items()):
                continue
            site = _folk_site(world, name, reach)
            if site is None:
                continue
            for k, n in spec["cost"].items():
                store[k] -= n
            built = {"kind": name, "x": site[0], "y": site[1], "by": "the folk", "day": world["day"]}
            world["built"].append(built)
            if name in ("field", "woodlot"):
                world["stocks"][f"{site[0]},{site[1]}"] = 0
            if name == "woodlot":
                world["woodlots"].append(f"{site[0]},{site[1]}")
            count[name] += 1
            stats["built"].append(name)
            done = True
            if name in ("hut", "stone_house") and folk + 2 + folk // 8 <= housing(world):
                wants = [w for w in wants if w not in ("hut", "stone_house")]
            break
        if not done:
            break


def _folk_day(world: dict, report: dict) -> None:
    """One day in the life of everyone who is not a named villager."""
    if not world["villagers"]:
        return
    world.setdefault("folk", 0)
    store, folk = world["store"], world["folk"]
    cx, cy = world["store_at"]
    reach = _folk_reach(world)
    stats = {"folk": folk, "food": 0, "wood": 0, "stone": 0, "born": 0, "starved": 0, "built": [], "reach": reach}
    if folk > 0:
        work = folk * boost(world, "work")
        winter = season(world) == "winter"
        count = Counter(b["kind"] for b in world["built"])
        # how much of each thing is worth fetching today
        want_food = max(0, folk * FOLK_LARDER[season(world)] - _edible(store))
        short_homes = folk + 2 + folk // 8 > housing(world)
        want_wood = max(0, 10 + folk // 2 + count["fire_pit"] * 3 + (12 if short_homes else 0) - store.get("wood", 0))
        want_stone = max(0, 6 + folk // 4 + (8 if short_homes else 0) - store.get("stone", 0))
        fish = boost(world, "fish")
        seen = world["villagers"][0]["seen"]
        for x, y in _rings(cx, cy, reach):
            if work <= 0 or not (want_food or want_wood or want_stone):
                break
            key = f"{x},{y}"
            kind = tile(world, x, y)
            stock = world["stocks"].get(key, 0)
            if want_food > 0 and stock > 0 and (kind == "berries" and not winter or kind == "grass" and key not in world["woodlots"]):
                wild = kind == "berries"
                take = min(stock, math.ceil(work), math.ceil(want_food / (1 if wild else boost(world, "food"))))
                world["stocks"][key] = stock - take
                gain = take if wild else math.ceil(take * boost(world, "food"))
                if not wild:
                    world["soil"][key] = max(0.3, world["soil"].get(key, 1.0) - SOIL_LOSS)
                store["food" if wild else "grain"] = store.get("food" if wild else "grain", 0) + gain
                stats["food"] += gain
                want_food -= gain
                work -= take
            elif want_food > 0 and fish and kind == "water":
                gain = min(math.ceil(work), 1 + int(fish), want_food)  # one stretch of water only gives so much
                store["food"] = store.get("food", 0) + gain
                stats["food"] += gain
                want_food -= gain
                work -= gain
            elif want_wood > 0 and stock > 0 and (kind == "forest" or key in world["woodlots"]):
                take = min(stock, math.ceil(work / 2), want_wood)
                if key in world["woodlots"]:
                    world["stocks"][key] = stock - take
                else:
                    take = _cut_tree(world, x, y, take)
                store["wood"] = store.get("wood", 0) + take
                stats["wood"] += take
                want_wood -= take
                work -= take * 2
            elif want_stone > 0 and kind == "rock":
                take = min(math.ceil(work / 3), want_stone, 4 + folk // 10)
                store["stone"] = store.get("stone", 0) + take
                stats["stone"] += take
                want_stone -= take
                work -= take * 3
            seen[key] = 1  # where the folk work is land the village knows
        # felled trees are not news once whole woods come down
        world["_events"] = [e for e in world.get("_events", []) if not e.startswith("The trees at")]
    _folk_build(world, stats, max(reach, FOLK_REACH + 3))
    if folk > 0:
        fed = 0
        for item in EDIBLE:
            eaten = min(store.get(item, 0), folk - fed)
            if eaten:
                store[item] -= eaten
                fed += eaten
        hungry = folk - fed
        if hungry:
            stats["starved"] = max(1, math.ceil(hungry * FOLK_STARVE_SHARE))
        elif season(world) == "winter" and not any(b["kind"] == "fire_pit" and b.get("lit", True) for b in world["built"]):
            stats["starved"] = max(1, folk // 20)  # the cold takes them without a fire
            report["events"].append(f"{stats['starved']} of the folk froze with no fire lit")
        if hungry:
            report["events"].append(f"{stats['starved']} of the folk starved")
        folk -= min(folk, stats["starved"])
    room = housing(world) - folk
    if room > 0 and folk == 0:
        stats["born"] = min(room, 2)  # the first family walks in, carrying what they have
        store["food"] = store.get("food", 0) + 4
    elif room > 0 and not stats["starved"] and _edible(store) >= folk * 2 and (stats["food"] >= folk or _edible(store) >= folk * 4):
        # children come when the store is full and the land is giving more than is eaten
        stats["born"] = min(room, max(1, round(folk * FOLK_BIRTH_RATE)))
    folk += stats["born"]
    before = world["folk"]
    world["folk"] = folk
    stats["folk"], stats["homes"] = folk, housing(world)
    world["folk_stats"] = stats
    report["folk"] = stats
    report["built"] += stats["built"]
    for mark in FOLK_MILESTONES:
        if before + len(world["villagers"]) < mark <= folk + len(world["villagers"]):
            world["guide"]["insight"] += 5 + mark // 50
            report["events"].append(f"{mark:,} people now live here (+{5 + mark // 50} Insight)")


def _focus_mark(world: dict) -> dict:
    return {"day": world["day"], "food": sum(_edible(v["inv"]) for v in world["villagers"]) + sum(_edible(inv) for _, _, inv in _stores(world)),
            "seen": sum(len(v["seen"]) for v in world["villagers"]), "built": len(world["built"]),
            "deaths": len(world["dead"]), "hungry": 0,
            "tries": sum(world["guide"]["attempts"].values())}


def _judge_focus(world: dict, report: dict) -> None:
    """Advice is measured by what happened, so Trust is earned rather than assumed."""
    guide, start = world["guide"], world["guide"]["focus_start"]
    now = _focus_mark(world)
    if guide["focus"] == "learn" and not [i for i in guide["planted"] if i not in guide["known"]]:
        guide["focus_start"] = now  # nothing to try is not bad advice
        return
    worked = {"food": start["hungry"] == 0 and now["food"] >= len(world["villagers"]),
              "shelter": now["built"] > start["built"],
              "explore": now["seen"] >= start["seen"] + 20,
              "learn": now["tries"] > start["tries"]}[guide["focus"]]
    lost = now["deaths"] > start["deaths"]
    change = -10 if lost else (5 if worked else -3)
    guide["trust"] = max(0, min(100, guide["trust"] + change))
    verdict = "someone died following it" if lost else ("it helped" if worked else "it did not help")
    report["events"].append(f"Your advice to {FOCUSES[guide['focus']]}: {verdict} (Trust {change:+d})")
    guide["focus_start"] = now


def _settle_guide(world: dict, report: dict, was_winter: bool) -> None:
    guide = world["guide"]
    if world["fallen"]:
        return
    gain = report["day"] % 2 + 3 * len(report["deaths"])  # quiet days earn slowly; events earn more
    kinds = [b["kind"] for b in world["built"]]
    gain += 3 * sum(1 for kind in set(report["built"]) if kinds.count(kind) == report["built"].count(kind))
    gain += 2 * sum(1 for e in report["events"] if e.endswith("looking for a home"))
    if was_winter and season(world) == "spring":
        gain += 5
        report["events"].append("The village came through the winter (+5 Insight)")
    gain += int(math.log2(world.get("folk", 0) + 1))  # more people notice more
    gain = round(gain * boost(world, "insight"))
    guide["insight"] += gain
    report["insight"] = gain
    if era(world) != guide["era"]:
        guide["era"] = era(world)
        guide["insight"] += 10
        report["events"].append(f"The {guide['era']} has begun (+10 Insight)")
    if guide["focus"]:
        guide["focus_start"]["hungry"] += sum(1 for e in report["villagers"] if not e["night"]["ate"])
        if world["day"] - guide["focus_start"]["day"] >= FOCUS_DAYS:
            _judge_focus(world, report)


def plant_idea(world: dict, idea: str) -> str | None:
    """Spend Insight to put an idea in the villagers' heads. Returns a refusal or None."""
    spec, guide = IDEAS.get(idea), world["guide"]
    if spec is None:
        return f"there is no idea called {idea!r}"
    if idea in guide["planted"]:
        return f"the villagers already have the idea of {spec['name'].lower()}"
    if any(n not in guide["known"] for n in spec["needs"]):
        return f"{spec['name']} builds on {', '.join(IDEAS[n]['name'] for n in spec['needs'])}, which they have not worked out"
    if guide["insight"] < spec["cost"]:
        return f"{spec['name']} costs {spec['cost']} Insight; you have {guide['insight']}"
    guide["insight"] -= spec["cost"]
    guide["planted"].append(idea)
    return None


def buy_upgrade(world: dict, upgrade: str) -> str | None:
    spec, guide = UPGRADES.get(upgrade), world["guide"]
    if spec is None:
        return f"there is no upgrade called {upgrade!r}"
    if upgrade in guide["upgrades"]:
        return f"the village already has {spec['name'].lower()}"
    if guide["insight"] < spec["cost"]:
        return f"{spec['name']} costs {spec['cost']} Insight; you have {guide['insight']}"
    guide["insight"] -= spec["cost"]
    guide["upgrades"].append(upgrade)
    for v in world["villagers"]:
        _reveal(world, v)
    return None


def set_focus(world: dict, focus: str | None) -> str | None:
    if focus is not None and focus not in FOCUSES:
        return f"focus must be one of {', '.join(FOCUSES)}"
    guide = world["guide"]
    guide["focus"] = focus
    guide["focus_start"] = _focus_mark(world) if focus else None
    return None


def legacy_earned(world: dict) -> int:
    """What a finished village leaves behind: its years, and everything it worked out."""
    return (world["day"] - 1) // (SEASON_DAYS * len(SEASONS)) + len(world["guide"]["known"]) + (1 if world["fallen"] else 0)


BEFORE_DAY = None  # set by village.policy: gives each villager the day's orders from their way


def run_day(world: dict, plans: dict[str, dict], source: str, unwatched: bool = False) -> dict:
    """Resolve one in-game day. ``plans`` maps villager name -> {actions, thought,
    remember, standing_orders}. Villagers without a plan follow their habit, then
    their instincts. Returns a report the page can replay, and advances the day.
    ``unwatched`` days can kill, but never the last villager: a village is only
    lost while someone is playing it."""
    if not plans and world["pending_plans"]:
        plans, source, world["pending_plans"] = world["pending_plans"], "model", None
    if BEFORE_DAY is not None:
        BEFORE_DAY(world)
    seen_before = _seen(world)
    report = {"day": world["day"], "source": source, "season": season(world), "villagers": [], "ok": 0,
              "rejected": 0, "gained": {}, "built": [], "events": [], "deaths": []}
    fatal: list[tuple[dict, str]] = []
    for v in world["villagers"]:
        plan = plans.get(v["name"])
        v["feedback"] = []
        if plan is None:
            actions = (list(v["standing_orders"]) + instinct_actions(world, v))[:MAX_ACTIONS]
            mode = "habit"
        else:
            actions, mode = list(plan.get("actions") or [])[:MAX_ACTIONS], source
            v["thought"] = str(plan.get("thought", ""))[:160]
            note = str(plan.get("remember", "")).strip()[:80]
            if note:
                v["memory"] = (v["memory"] + [f"day {world['day']}: {note}"])[-_memory_lines(world):]
            orders = plan.get("standing_orders")
            if isinstance(orders, list):
                v["standing_orders"] = [a for a in orders if isinstance(a, dict) and a.get("verb") in VERBS][:3]
        entry = {"name": v["name"], "mode": mode, "start": _pose(v), "steps": [],
                 "thought": v["thought"] if mode != "habit" else ""}
        slots = SLOTS_PER_DAY
        for act in actions:
            if slots <= 0:
                break
            if mode == "habit" and isinstance(act, dict) and act.get("verb") == "build" \
                    and not _can_build(world, v, act):
                continue  # a habit waits for materials instead of failing every day
            if mode == "habit" and isinstance(act, dict) and act.get("verb") == "gather"                     and act.get("item") == "food" and not _ready_food(world, v):
                continue  # the bush ran out mid-picking; nothing to fail at
            if mode == "habit" and isinstance(act, dict) and _nothing_to_do(world, v, act):
                continue
            fx: dict = {}
            used, err, summary = execute(world, v, act, slots, fx)
            entry["steps"].append({"action": act if isinstance(act, dict) else {}, "ok": err is None,
                                   "result": err or summary, "at": SLOTS_PER_DAY - slots, "slots": used,
                                   "after": _pose(v), **fx})
            slots -= used
            if err:
                v["feedback"].append(err)
                report["rejected"] += 1
            else:
                report["ok"] += 1
                for k, n in fx.get("gain", {}).items():
                    report["gained"][k] = report["gained"].get(k, 0) + n
                if "built" in fx:
                    report["built"].append(fx["built"]["kind"])
        cause = _night(world, v, entry)
        if cause and unwatched and len(fatal) + 1 >= len(world["villagers"]):
            v["health"] = 1
            entry["night"]["health"] = 1
            cause = None
        if cause:
            fatal.append((v, cause))
        v["heard"] = v["heard"][-HEARD_LINES:]
        report["villagers"].append(entry)
    for v, cause in fatal:
        world["villagers"].remove(v)
        record = {k: val for k, val in v.items() if k != "seen"}
        record.update(cause=cause, day=world["day"])
        world["dead"].append(record)
        report["deaths"].append({"name": v["name"], "cause": cause})
        report["events"].append(f"{v['name']} died of {cause}")
    _folk_day(world, report)
    _burn_fuel(world, report["events"])
    if not any(b["kind"] in ("storehouse", "drying_rack") for b in world["built"]):
        for _, _, inv in _stores(world):
            _rot(inv)
    report["events"] = world.pop("_events", []) + report["events"]
    _grow(world)
    if world["villagers"]:
        _arrival(world, report["events"])
    else:
        world["fallen"] = world["day"]
        report["events"].append("The village has fallen")
    report["revealed"] = sorted(_seen(world) - seen_before)
    world["log"] = (world["log"] + [report])[-12:]
    world["land_rev"] += 1
    was_winter = season(world) == "winter"
    world["day"] += 1
    if not world["fallen"] and (world["day"] - 1) % SEASON_DAYS == 0:
        report["events"].append(f"{season(world).capitalize()} is here")
    _settle_guide(world, report, was_winter)
    return report


def _at_normal_speed(world: dict) -> bool:
    return world["speed"] == 1 and world["paused_at"] is None


def _unpause(world: dict, now: float) -> None:
    if world["paused_at"] is not None:
        world["day_started_at"] += now - world["paused_at"]
        world["paused_at"] = None


def _set_rate(world: dict, speed: int, now: float) -> None:
    """Change speed mid-day without moving anyone: keep the share of the day already played."""
    played = (now - world["day_started_at"]) * world["speed"]
    world["day_started_at"] = now - played / speed
    world["speed"] = speed


def set_speed(world: dict, speed: Any, now: float) -> str | None:
    """Speed 0 pauses. Returns a refusal or None."""
    if speed != 0 and speed not in SPEEDS:
        return f"speed must be 0 (pause) or one of {', '.join(map(str, SPEEDS))}"
    world["last_read"] = now
    if speed == 0:
        if world["paused_at"] is None:
            world["paused_at"] = now
        return None
    _unpause(world, now)
    _set_rate(world, speed, now)
    return None


def restart_day(world: dict, now: float) -> None:
    """A new day was just resolved by hand: its playback starts now, even while paused."""
    world["day_started_at"] = now
    if world["paused_at"] is not None:
        world["paused_at"] = now


def _drop_idle_speed(world: dict, now: float) -> bool:
    """Speed and pause need someone watching. Once they leave, time since their last
    look runs at 1x, so closing the page at 16x cannot race the village ahead."""
    if _at_normal_speed(world):
        return False
    seen = world["last_read"]
    world["last_read"] = now
    if now - seen > SPEED_IDLE_SECONDS:
        _unpause(world, seen)
        _set_rate(world, 1, seen)
    return True


def advance(world: dict, now: float) -> dict | None:
    """Bring the clock up to ``now``: free days only, never a model call. Returns a
    digest when the village lived through two or more days since it was last seen."""
    changed = _drop_idle_speed(world, now)
    if not world["log"]:
        run_day(world, {}, source="habit")
        world["day_started_at"] = now
        changed = True
    if world["paused_at"] is not None:
        world["_dirty"] = changed
        return None
    days, gained, built, deaths = 0, {}, [], []
    step = DAY_SECONDS / world["speed"]
    while now - world["day_started_at"] >= step and days < MAX_CATCHUP_DAYS and not world["fallen"]:
        catching_up = world["speed"] == 1 and now - world["day_started_at"] >= 2 * step
        report = run_day(world, {}, source="habit", unwatched=catching_up)
        world["day_started_at"] += step
        days += 1
        changed = True
        for k, n in report["gained"].items():
            gained[k] = gained.get(k, 0) + n
        built += report["built"]
        deaths += report["deaths"]
    if now - world["day_started_at"] >= step and not world["fallen"]:  # a long absence: the rest is uneventful
        world["day_started_at"] = now
        changed = True
    world["_dirty"] = changed
    if days < 2 or world["speed"] > 1:
        return None
    away = world["away"] or {"days": 0, "gained": {}, "built": [], "deaths": []}
    for k, n in gained.items():
        away["gained"][k] = away["gained"].get(k, 0) + n
    away["days"] += days
    away["built"] += built
    away["deaths"] += deaths
    world["away"] = away
    return away


def settlement(world: dict) -> str:
    name = LEVELS[0][1]
    for need, label in LEVELS:
        if len(world["built"]) >= need:
            name = label
    for need, label in TOWNS:
        if population(world) >= need:
            name = label
    return name


def needs_council(world: dict, held: dict | None = None) -> list[str]:
    """Reasons the village would benefit from a model-planned day. Empty means the
    villagers can carry on by themselves. Rejections alone do not force a call."""
    reasons = []
    if world["fallen"] or world["pending_plans"]:
        return reasons
    if world["last_planned_day"] == 0:
        reasons.append("the village has never held a council")
    if world["guidance"] and world["guidance_day"] > world["last_planned_day"]:
        reasons.append("you gave new guidance")
    waiting = [IDEAS[i]["name"].lower() for i in world["guide"]["planted"] if i not in world["guide"]["known"]]
    if waiting:
        reasons.append(f"{', '.join(waiting)} is waiting to be tried")
    starving = [v["name"] for v in world["villagers"] if v["hungry"] >= 2 or v["health"] <= 2]
    if starving:
        reasons.append(f"{', '.join(starving)} may not survive much longer")
    day_of_season = (world["day"] - 1) % SEASON_DAYS
    if season(world) == "autumn" and day_of_season >= 2 and sum(v["inv"].get("food", 0) for v in world["villagers"]) < 4 * len(world["villagers"]):
        reasons.append("winter is close and there is not enough food")
    wild = (held or resources(world))["wild"]
    if wild["wood"] < 10:
        reasons.append("they know of very little wood left nearby")
    if world["fire_out"]:
        reasons.append("the fire is out")
    tired = [v["name"] for v in world["villagers"] if len(v["feedback"]) >= 3]
    if tired:
        reasons.append(f"{', '.join(tired)} keep failing")
    return reasons


def _seen(world: dict) -> set[str]:
    return set().union(*(v["seen"] for v in world["villagers"])) if world["villagers"] else set()


def land_rev(world: dict) -> str:
    """Changes whenever the land the page holds goes out of date, and for every new village."""
    return f"{world['seed']}:{world['born']}:{world['land_rev']}"


def land_view(world: dict) -> dict:
    """Only what has been seen, plus the chunks around it so the ground can be drawn right up to
    the edge of the dark. Nothing further out exists yet, so nothing further out can leak."""
    seen = _seen(world)
    masks: dict[tuple[int, int], bytearray] = {}
    for key in seen:
        x, y = map(int, key.split(","))
        at = (x >> 4, y >> 4)
        if at not in masks:
            masks[at] = bytearray(b"0" * (CHUNK * CHUNK))
        masks[at][(y & 15) * CHUNK + (x & 15)] = 49
    near = {(cx + dx, cy + dy) for cx, cy in masks for dy in (-1, 0, 1) for dx in (-1, 0, 1)}
    land = {at: list("".join(_land(world["seed"], *at))) for at in near}
    for key, char in world["shaped"].items():  # the camp's clearing is part of the land, cut or not
        x, y = map(int, key.split(","))
        if (x >> 4, y >> 4) in land:
            land[(x >> 4, y >> 4)][(y & 15) * CHUNK + (x & 15)] = char
    return {"rev": land_rev(world), "land": {f"{cx},{cy}": "".join(chars) for (cx, cy), chars in land.items()},
            "seen": {f"{cx},{cy}": mask.decode() for (cx, cy), mask in masks.items()},
            "stocks": {k: n for k, n in world["stocks"].items() if k in seen}}


def resources(world: dict) -> dict:
    """What the village holds, and what it knows is still out there. Unexplored land does not count."""
    stores = [inv for _, _, inv in _stores(world)]
    packs = [v["inv"] for v in world["villagers"]] + stores
    held = {"food": sum(_edible(p) for p in packs), "wood": sum(p.get("wood", 0) for p in packs),
            "stone": sum(p.get("stone", 0) for p in packs)}
    seen = _seen(world)
    wild = {"food": 0, "wood": 0, "stone": 0}
    changed, land_seed, woodlots = world["changed"], world["seed"], world["woodlots"]

    def char(key: str) -> str:  # this runs on every poll over everything ever seen
        known = changed.get(key)
        if known:
            return known
        x, y = key.split(",")
        return _land_char(land_seed, int(x), int(y))
    for key, stock in world["stocks"].items():
        if key in seen:
            wild["wood" if char(key) == "T" or key in woodlots else "food"] += stock
    wild["stone"] = sum(1 for key in seen if char(key) == "R")
    herds = [h for h in world["herds"] if f"{h['x']},{h['y']}" in seen]
    stored: dict[str, int] = {}
    for inv in stores:
        for item, n in inv.items():
            stored[item] = stored.get(item, 0) + n
    return {"held": held, "stored": stored, "wild": wild, "herds": herds, "fire_out": world["fire_out"]}


def _light_report(report: dict) -> dict:
    """Older days for the log: results only, no replay data."""
    return {**report, "villagers": [
        {"name": e["name"], "mode": e["mode"], "thought": e["thought"],
         "steps": [{"action": s["action"], "ok": s["ok"], "result": s["result"]} for s in e["steps"]]}
        for e in report["villagers"]]}


def public_state(world: dict, now: float, have: str = "") -> dict:
    """What the page may show. The page is the player's god-view; villagers' prompts
    use observe() instead. ``villagers`` and ``built`` are end-of-day truth; the page
    reveals them step by step from ``current`` as the day plays. ``have`` is the land
    revision the page already holds: the land only changes once a day, so most polls skip it."""
    current = world["log"][-1] if world["log"] else None
    rev = land_rev(world)
    held = resources(world)
    fields = ("name", "trait", "x", "y", "energy", "health", "hungry", "skills", "inv",
              "memory", "heard", "feedback", "standing_orders", "thought")
    dying = [{**{k: d[k] for k in fields}, "dying": d["cause"], "seen_count": 0}
             for d in world["dead"] if current and d["day"] == current["day"]]
    return {
        "schema": world["schema"], "day": current["day"] if current else world["day"],
        "land_id": f"{world['seed']}:{world['born']}", "land_rev": rev, "camp": world["camp"],
        "built": world["built"], "guidance": world["guidance"],
        "resources": held, "store_at": world["store_at"],
        **({} if have == rev else {"land_view": land_view(world)}),
        "vision": _vision(world), "dawn_fraction": DAWN_FRACTION, "chunk": CHUNK,
        "depots": [[d["x"], d["y"]] for d in world["depots"]],
        "council_ready": bool(world["pending_plans"]),
        "stock_full": {TILE_CHARS[k]: n for k, n in FULL_STOCK.items()},
        "settlement": settlement(world), "buildings": BUILDINGS,
        "folk": world.get("folk", 0), "population": population(world), "homes": housing(world),
        "folk_stats": world.get("folk_stats"), "eras": ERAS,
        "boosts": {k: boost(world, k) for k in ("work", "food", "housing", "reach", "insight")},
        "now": now, "day_started_at": world["day_started_at"], "day_seconds": DAY_SECONDS,
        "speed": world["speed"], "paused_at": world["paused_at"], "speeds": SPEEDS,
        "work_fraction": WORK_FRACTION, "slots_per_day": SLOTS_PER_DAY,
        "current": current, "away": world["away"],
        "villagers": [{k: v[k] for k in fields} | {"seen_count": len(v["seen"])} for v in world["villagers"]] + dying,
        "season": current["season"] if current else season(world), "season_days": SEASON_DAYS,
        "fallen": world["fallen"],
        "max_health": max_health(world),
        "guide": {**{k: world["guide"][k] for k in ("insight", "trust", "focus", "planted", "known", "upgrades", "era", "attempts")},
                  "ideas": IDEAS, "upgrades_for_sale": UPGRADES, "focuses": FOCUSES, "future_eras": FUTURE_ERAS,
                  "trust_heeded": TRUST_HEEDED, "focus_days": FOCUS_DAYS},
        "dead": [{k: d[k] for k in ("name", "day", "cause", "x", "y")} for d in world["dead"]],
        "log": [_light_report(r) for r in world["log"][-10:]],
        "council_reasons": needs_council(world, held),
    }
