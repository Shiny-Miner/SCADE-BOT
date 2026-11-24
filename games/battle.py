"""
Battle engine (no Discord, no database): type chart, moves, damage and turn resolution.

Moves are generated from a pokémon's types and level (so it works for all 1025 species
without downloading learnsets): up to 4 damaging moves, stronger ones unlock as it levels.
"""

import random
from dataclasses import dataclass, field

from games.pokedata import calc_stats

# ------------------------------------------------------------------ type chart
# attacker type -> {defender type: multiplier}. Anything not listed is 1x.
CHART = {
    "normal": {"rock": .5, "steel": .5, "ghost": 0},
    "fire": {"fire": .5, "water": .5, "grass": 2, "ice": 2, "bug": 2, "rock": .5, "dragon": .5, "steel": 2},
    "water": {"fire": 2, "water": .5, "grass": .5, "ground": 2, "rock": 2, "dragon": .5},
    "electric": {"water": 2, "electric": .5, "grass": .5, "ground": 0, "flying": 2, "dragon": .5},
    "grass": {"fire": .5, "water": 2, "grass": .5, "poison": .5, "ground": 2, "flying": .5, "bug": .5, "rock": 2,
              "dragon": .5, "steel": .5},
    "ice": {"fire": .5, "water": .5, "grass": 2, "ice": .5, "ground": 2, "flying": 2, "dragon": 2, "steel": .5},
    "fighting": {"normal": 2, "ice": 2, "poison": .5, "flying": .5, "psychic": .5, "bug": .5, "rock": 2, "ghost": 0,
                 "dark": 2, "steel": 2, "fairy": .5},
    "poison": {"grass": 2, "poison": .5, "ground": .5, "rock": .5, "ghost": .5, "steel": 0, "fairy": 2},
    "ground": {"fire": 2, "electric": 2, "grass": .5, "poison": 2, "flying": 0, "bug": .5, "rock": 2, "steel": 2},
    "flying": {"electric": .5, "grass": 2, "fighting": 2, "bug": 2, "rock": .5, "steel": .5},
    "psychic": {"fighting": 2, "poison": 2, "psychic": .5, "dark": 0, "steel": .5},
    "bug": {"fire": .5, "grass": 2, "fighting": .5, "poison": .5, "flying": .5, "psychic": 2, "ghost": .5, "dark": 2,
            "steel": .5, "fairy": .5},
    "rock": {"fire": 2, "ice": 2, "fighting": .5, "ground": .5, "flying": 2, "bug": 2, "steel": .5},
    "ghost": {"normal": 0, "psychic": 2, "ghost": 2, "dark": .5},
    "dragon": {"dragon": 2, "steel": .5, "fairy": 0},
    "dark": {"fighting": .5, "psychic": 2, "ghost": 2, "dark": .5, "fairy": .5},
    "steel": {"fire": .5, "water": .5, "electric": .5, "ice": 2, "rock": 2, "steel": .5, "fairy": 2},
    "fairy": {"fire": .5, "fighting": 2, "poison": .5, "dragon": 2, "dark": 2, "steel": .5},
}

# Older games decided physical/special by TYPE, which keeps this simple.
PHYSICAL_TYPES = {"normal", "fighting", "flying", "ground", "rock", "bug", "ghost", "poison", "steel"}

# four moves per type, weakest -> strongest
MOVE_NAMES = {
    "normal": ["Tackle", "Slam", "Body Slam", "Hyper Beam"],
    "fire": ["Ember", "Flame Wheel", "Flamethrower", "Fire Blast"],
    "water": ["Water Gun", "Bubble Beam", "Surf", "Hydro Pump"],
    "electric": ["Thunder Shock", "Spark", "Thunderbolt", "Thunder"],
    "grass": ["Vine Whip", "Razor Leaf", "Energy Ball", "Solar Beam"],
    "ice": ["Powder Snow", "Ice Shard", "Ice Beam", "Blizzard"],
    "fighting": ["Karate Chop", "Low Sweep", "Brick Break", "Close Combat"],
    "poison": ["Poison Sting", "Acid", "Sludge Bomb", "Gunk Shot"],
    "ground": ["Mud-Slap", "Bulldoze", "Earthquake", "Precipice Blades"],
    "flying": ["Gust", "Wing Attack", "Air Slash", "Brave Bird"],
    "psychic": ["Confusion", "Psybeam", "Psychic", "Future Sight"],
    "bug": ["Bug Bite", "Struggle Bug", "X-Scissor", "Megahorn"],
    "rock": ["Rock Throw", "Rock Slide", "Power Gem", "Stone Edge"],
    "ghost": ["Lick", "Shadow Sneak", "Shadow Ball", "Shadow Force"],
    "dragon": ["Twister", "Dragon Breath", "Dragon Pulse", "Draco Meteor"],
    "dark": ["Bite", "Snarl", "Crunch", "Foul Play"],
    "steel": ["Metal Claw", "Steel Wing", "Iron Head", "Flash Cannon"],
    "fairy": ["Fairy Wind", "Disarming Voice", "Dazzling Gleam", "Moonblast"],
}
TIER_POWER = [40, 65, 90, 110]
TIER_ACCURACY = [100, 100, 100, 85]
TIER_LEVELS = [1, 15, 30, 50]  # level needed to unlock each tier

TYPE_EMOJI = {
    "normal": "⚪", "fire": "🔥", "water": "💧", "electric": "⚡", "grass": "🌿", "ice": "❄️", "fighting": "🥊",
    "poison": "☠️", "ground": "⛰️", "flying": "🪽", "psychic": "🔮", "bug": "🐛", "rock": "🪨", "ghost": "👻",
    "dragon": "🐉", "dark": "🌑", "steel": "⚙️", "fairy": "🧚",
}

CRIT_CHANCE = 1 / 16
MAX_TEAM = 3


@dataclass(frozen=True)
class Move:
    name: str
    type: str
    power: int
    accuracy: int

    @property
    def category(self) -> str:
        return "physical" if self.type in PHYSICAL_TYPES else "special"

    def label(self) -> str:
        return f"{TYPE_EMOJI.get(self.type, '')} {self.name}"


def make_move(type_name: str, tier: int) -> Move:
    return Move(MOVE_NAMES[type_name][tier], type_name, TIER_POWER[tier], TIER_ACCURACY[tier])


def unlocked_tiers(level: int) -> int:
    return sum(1 for need in TIER_LEVELS if level >= need)


def moves_for(types, level: int):
    """Up to 4 moves from the pokémon's types (plus Normal coverage), best unlocked tiers first."""
    top = unlocked_tiers(level) - 1  # highest unlocked tier index
    candidates = []
    for offset in (0, 1):
        for t in types:
            if top - offset >= 0:
                candidates.append(make_move(t, top - offset))
    for offset in (0, 1):  # Normal coverage fills any gaps
        if top - offset >= 0:
            candidates.append(make_move("normal", top - offset))
    moves, seen = [], set()
    for move in candidates:
        if move.name not in seen:
            seen.add(move.name)
            moves.append(move)
        if len(moves) == 4:
            break
    return moves


def effectiveness(move_type: str, defender_types) -> float:
    mult = 1.0
    for d in defender_types:
        mult *= CHART.get(move_type, {}).get(d, 1)
    return mult


# ---------------------------------------------------------------- combatants
@dataclass
class Combatant:
    pokemon_id: int
    species_id: int
    name: str
    level: int
    types: list
    stats: dict
    moves: list
    max_hp: int = 0
    hp: int = 0
    shiny: bool = False

    def __post_init__(self):
        self.max_hp = self.stats["hp"]
        self.hp = self.max_hp

    @property
    def fainted(self) -> bool:
        return self.hp <= 0


def build_combatant(row, species, name) -> Combatant:
    """row = pokémon database row, species = cached species data (types, base stats)."""
    ivs = {k: row[f"iv_{k}"] for k in ("hp", "atk", "def", "spa", "spd", "spe")}
    stats = calc_stats(species["base"], ivs, row["level"], row["nature"])
    return Combatant(
        pokemon_id=row["id"], species_id=row["species_id"], name=row["nickname"] or name, level=row["level"],
        types=list(species["types"]), stats=stats, moves=moves_for(species["types"], row["level"]),
        shiny=bool(row["shiny"]),
    )


def calc_damage(attacker: Combatant, defender: Combatant, move: Move, rng=random):
    """Returns (damage, effectiveness, critical)."""
    eff = effectiveness(move.type, defender.types)
    if eff == 0:
        return 0, 0.0, False
    if move.category == "physical":
        atk, dfn = attacker.stats["atk"], defender.stats["def"]
    else:
        atk, dfn = attacker.stats["spa"], defender.stats["spd"]
    base = ((2 * attacker.level / 5 + 2) * move.power * atk / max(1, dfn)) / 50 + 2
    stab = 1.5 if move.type in attacker.types else 1.0
    crit = rng.random() < CRIT_CHANCE
    roll = rng.uniform(0.85, 1.0)
    dmg = int(base * stab * eff * (1.5 if crit else 1.0) * roll)
    return max(1, dmg), eff, crit


# -------------------------------------------------------------------- battle
@dataclass
class Side:
    user_id: int
    name: str
    team: list
    active: int = 0
    forfeited: bool = False

    @property
    def current(self) -> Combatant:
        return self.team[self.active]

    @property
    def alive(self) -> int:
        return sum(1 for c in self.team if not c.fainted)

    @property
    def defeated(self) -> bool:
        return self.forfeited or self.alive == 0


@dataclass
class Battle:
    a: Side
    b: Side
    rng: random.Random = field(default_factory=random.Random)
    turn: int = 1
    log: list = field(default_factory=list)

    @property
    def over(self) -> bool:
        return self.a.defeated or self.b.defeated

    @property
    def winner(self):
        """The winning Side, or None if the battle isn't over."""
        if not self.over:
            return None
        if self.a.defeated and self.b.defeated:
            return None  # can't happen with the current rules, but be safe
        return self.b if self.a.defeated else self.a

    def _attack(self, att_side: Side, def_side: Side, move: Move):
        att, dfn = att_side.current, def_side.current
        if att.fainted or dfn.fainted:
            return
        if self.rng.random() * 100 >= move.accuracy:
            self.log.append(f"{att.name} used **{move.name}** but it missed!")
            return
        dmg, eff, crit = calc_damage(att, dfn, move, self.rng)
        dmg = min(dmg, dfn.hp)
        dfn.hp -= dmg
        text = f"{att.name} used **{move.name}** for **{dmg}** damage"
        if eff == 0:
            text = f"{att.name} used **{move.name}**. It doesn't affect {dfn.name}..."
        elif eff > 1:
            text += " (super effective!)"
        elif eff < 1:
            text += " (not very effective)"
        if crit and eff:
            text += " 💥 Critical hit!"
        self.log.append(text)
        if dfn.fainted:
            self.log.append(f"💀 **{dfn.name}** fainted!")
            nxt = next((i for i, c in enumerate(def_side.team) if not c.fainted), None)
            if nxt is not None:
                def_side.active = nxt
                self.log.append(f"{def_side.name} sent out **{def_side.current.name}**!")

    def resolve_turn(self, move_a: Move, move_b: Move):
        """Both sides chose a move: the faster pokémon goes first. Returns this turn's log lines."""
        self.log = []
        first_a = self.a.current.stats["spe"] > self.b.current.stats["spe"]
        if self.a.current.stats["spe"] == self.b.current.stats["spe"]:
            first_a = self.rng.random() < 0.5
        order = [(self.a, self.b, move_a), (self.b, self.a, move_b)]
        if not first_a:
            order.reverse()
        # A pokémon replaced mid-turn (after a faint) doesn't get a free attack
        starters = {id(order[0][0]): order[0][0].current, id(order[1][0]): order[1][0].current}
        for att_side, def_side, move in order:
            if self.over:
                break
            if att_side.current is not starters[id(att_side)] or att_side.current.fainted:
                continue
            self._attack(att_side, def_side, move)
        self.turn += 1
        return list(self.log)

    def forfeit(self, user_id: int):
        for side in (self.a, self.b):
            if side.user_id == user_id:
                side.forfeited = True
                self.log = [f"🏳️ **{side.name}** forfeited the battle!"]
                return self.log
        return []


def hp_bar(hp: int, max_hp: int, width: int = 10) -> str:
    filled = 0 if hp <= 0 else max(1, round(hp / max_hp * width))
    return "█" * filled + "░" * (width - filled)


def random_move(combatant: Combatant, rng=random) -> Move:
    return rng.choice(combatant.moves)
