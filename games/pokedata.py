"""
Pure game logic + PokeAPI client for the Pokémon game.
Nothing in here talks to Discord, so it is easy to test.
"""

import asyncio
import random
import re
import unicodedata

import aiohttp

API = "https://pokeapi.co/api/v2"
ARTWORK = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/"
MAX_SPECIES = 1025
MAX_LEVEL = 100

# ------------------------------------------------------------------ stats
STAT_ORDER = ["hp", "atk", "def", "spa", "spd", "spe"]
STAT_LABEL = {"hp": "HP", "atk": "Attack", "def": "Defense", "spa": "Sp. Atk", "spd": "Sp. Def", "spe": "Speed"}
API_STAT = {
    "hp": "hp", "attack": "atk", "defense": "def",
    "special-attack": "spa", "special-defense": "spd", "speed": "spe",
}

# nature -> (boosted stat, lowered stat)
NATURES = {
    "Hardy": (None, None), "Lonely": ("atk", "def"), "Brave": ("atk", "spe"), "Adamant": ("atk", "spa"),
    "Naughty": ("atk", "spd"), "Bold": ("def", "atk"), "Docile": (None, None), "Relaxed": ("def", "spe"),
    "Impish": ("def", "spa"), "Lax": ("def", "spd"), "Timid": ("spe", "atk"), "Hasty": ("spe", "def"),
    "Serious": (None, None), "Jolly": ("spe", "spa"), "Naive": ("spe", "spd"), "Modest": ("spa", "atk"),
    "Mild": ("spa", "def"), "Quiet": ("spa", "spe"), "Bashful": (None, None), "Rash": ("spa", "spd"),
    "Calm": ("spd", "atk"), "Gentle": ("spd", "def"), "Sassy": ("spd", "spe"), "Careful": ("spd", "spa"),
    "Quirky": (None, None),
}

TYPE_COLORS = {
    "normal": 0xA8A77A, "fire": 0xEE8130, "water": 0x6390F0, "electric": 0xF7D02C, "grass": 0x7AC74C,
    "ice": 0x96D9D6, "fighting": 0xC22E28, "poison": 0xA33EA1, "ground": 0xE2BF65, "flying": 0xA98FF3,
    "psychic": 0xF95587, "bug": 0xA6B91A, "rock": 0xB6A136, "ghost": 0x735797, "dragon": 0x6F35FC,
    "dark": 0x705746, "steel": 0xB7B7CE, "fairy": 0xD685AD,
}

# ------------------------------------------------------- rarity (by dex number)
LEGENDARY = {
    144, 145, 146, 150, 243, 244, 245, 249, 250, 377, 378, 379, 380, 381, 382, 383, 384,
    480, 481, 482, 483, 484, 485, 486, 487, 488, 638, 639, 640, 641, 642, 643, 644, 645, 646,
    716, 717, 718, 772, 773, 785, 786, 787, 788, 789, 790, 791, 792, 800,
    888, 889, 890, 891, 892, 894, 895, 896, 897, 898, 905, 1001, 1002, 1003, 1004, 1007, 1008, 1024,
}
MYTHICAL = {
    151, 251, 385, 386, 489, 490, 491, 492, 493, 494, 647, 648, 649, 719, 720, 721,
    801, 802, 807, 808, 809, 893, 1025,
}
ULTRA_BEASTS = {793, 794, 795, 796, 797, 798, 799, 803, 804, 805, 806}


def rarity_of(species_id: int) -> str:
    if species_id in MYTHICAL:
        return "Mythical"
    if species_id in LEGENDARY:
        return "Legendary"
    if species_id in ULTRA_BEASTS:
        return "Ultra Beast"
    return "Common"


_RARITY_WEIGHT = {"Common": 1.0, "Legendary": 0.12, "Mythical": 0.08, "Ultra Beast": 0.12}


def pick_species(ids):
    """Random species id; legendaries/mythicals/ultra beasts are rare."""
    ids = list(ids)
    weights = [_RARITY_WEIGHT[rarity_of(i)] for i in ids]
    return random.choices(ids, weights=weights, k=1)[0]


# ---------------------------------------------------------------- starters
STARTERS = {
    "Kanto": ["bulbasaur", "charmander", "squirtle"],
    "Johto": ["chikorita", "cyndaquil", "totodile"],
    "Hoenn": ["treecko", "torchic", "mudkip"],
    "Sinnoh": ["turtwig", "chimchar", "piplup"],
    "Unova": ["snivy", "tepig", "oshawott"],
    "Kalos": ["chespin", "fennekin", "froakie"],
    "Alola": ["rowlet", "litten", "popplio"],
    "Galar": ["grookey", "scorbunny", "sobble"],
    "Paldea": ["sprigatito", "fuecoco", "quaxly"],
}
STARTER_IDS = {
    "bulbasaur": 1, "charmander": 4, "squirtle": 7, "chikorita": 152, "cyndaquil": 155, "totodile": 158,
    "treecko": 252, "torchic": 255, "mudkip": 258, "turtwig": 387, "chimchar": 390, "piplup": 393,
    "snivy": 495, "tepig": 498, "oshawott": 501, "chespin": 650, "fennekin": 653, "froakie": 656,
    "rowlet": 722, "litten": 725, "popplio": 728, "grookey": 810, "scorbunny": 813, "sobble": 816,
    "sprigatito": 906, "fuecoco": 909, "quaxly": 912,
}

# -------------------------------------------------------------------- names
_PRETTY = {
    "nidoran-f": "Nidoran♀", "nidoran-m": "Nidoran♂", "mr-mime": "Mr. Mime", "mime-jr": "Mime Jr.",
    "mr-rime": "Mr. Rime", "farfetchd": "Farfetch'd", "sirfetchd": "Sirfetch'd", "ho-oh": "Ho-Oh",
    "porygon-z": "Porygon-Z", "type-null": "Type: Null", "flabebe": "Flabébé", "jangmo-o": "Jangmo-o",
    "hakamo-o": "Hakamo-o", "kommo-o": "Kommo-o", "wo-chien": "Wo-Chien", "chien-pao": "Chien-Pao",
    "ting-lu": "Ting-Lu", "chi-yu": "Chi-Yu",
}


def pretty_name(slug: str) -> str:
    if slug in _PRETTY:
        return _PRETTY[slug]
    return slug.replace("-", " ").title()


def norm(text: str) -> str:
    """Lowercase letters/digits only, accents removed: 'Flabébé' == 'flabebe' == 'FLABEBE'."""
    text = text.lower().replace("♀", "f").replace("♂", "m")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if c.isalnum())


def accepted_guesses(slug: str) -> set:
    return {norm(slug), norm(pretty_name(slug))}


def artwork_url(species_id: int, shiny: bool = False) -> str:
    return f"{ARTWORK}{'shiny/' if shiny else ''}{species_id}.png"


def make_hint(name: str, order, reveal: int) -> str:
    """Pokétwo-style hint: reveals `reveal` letters (in a fixed random order) and hides the rest."""
    shown = set(order[:reveal])
    out = []
    for i, ch in enumerate(name):
        if not ch.isalpha():
            out.append(" " if ch == " " else ch)
        else:
            out.append(ch.lower() if i in shown else "\\_")
    return " ".join(out)


def hint_reveal_count(name: str) -> int:
    letters = sum(c.isalpha() for c in name)
    return max(1, (letters * 2) // 5)


# --------------------------------------------------------------- generation
def random_ivs() -> dict:
    return {k: random.randint(0, 31) for k in STAT_ORDER}


def random_nature() -> str:
    return random.choice(list(NATURES))


def iv_percent(ivs: dict) -> float:
    return round(sum(ivs[k] for k in STAT_ORDER) / 186 * 100, 2)


def calc_stats(base: dict, ivs: dict, level: int, nature: str) -> dict:
    plus, minus = NATURES.get(nature, (None, None))
    out = {}
    for k in STAT_ORDER:
        b, iv = base.get(k, 50), ivs[k]
        if k == "hp":
            out[k] = ((2 * b + iv) * level) // 100 + level + 10
        else:
            v = ((2 * b + iv) * level) // 100 + 5
            if k == plus:
                v = int(v * 1.1)
            elif k == minus:
                v = int(v * 0.9)
            out[k] = v
    return out


def xp_needed(level: int) -> int:
    """XP required to go from `level` to `level + 1`."""
    return 40 + level * level


def shiny_chance(streak: int = 0) -> float:
    """1/4096 base. Every catch of your hunted pokémon raises it, up to 10x at a 300 streak."""
    return (1 / 4096) * (1 + min(max(streak, 0), 300) * 9 / 300)


FRIENDSHIP_LEVEL = 20  # pokémon that evolve by friendship (Eevee, Pichu...) evolve at this level here


def level_evolution(evolutions, level: int):
    """Pick an evolution that triggers by level-up (or friendship) at or below `level`, or None."""
    ok = []
    for e in evolutions or []:
        if e.get("trigger") != "level-up" or e.get("item") or e.get("held_item"):
            continue
        if e.get("level"):
            if e["level"] <= level:
                ok.append(e)
        elif e.get("happiness") and level >= FRIENDSHIP_LEVEL:
            ok.append(e)
    return random.choice(ok) if ok else None


def item_evolution(evolutions, item_name: str):
    """Evolution that happens when using this evolution stone (e.g. 'fire-stone'), or None."""
    for e in evolutions or []:
        if e.get("trigger") == "use-item" and e.get("item") == item_name:
            return e
    return None


def trade_evolution(evolutions):
    """Evolution that happens when traded (no held item / partner species needed), or None."""
    for e in evolutions or []:
        if e.get("trigger") == "trade" and not e.get("item") and not e.get("held_item") and not e.get("trade_species"):
            return e
    return None


# ------------------------------------------------------------------ PokeAPI
def _id_from_url(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _find_node(node, species_id):
    if _id_from_url(node["species"]["url"]) == species_id:
        return node
    for child in node.get("evolves_to", []):
        found = _find_node(child, species_id)
        if found:
            return found
    return None


def extract_evolutions(chain_root, species_id):
    node = _find_node(chain_root, species_id)
    result = []
    for child in (node or {}).get("evolves_to", []):
        details = child.get("evolution_details") or [{}]
        level_detail = next(
            (d for d in details if (d.get("trigger") or {}).get("name") == "level-up" and d.get("min_level")),
            None,
        )
        d = level_detail or details[0]
        result.append({
            "to": _id_from_url(child["species"]["url"]),
            "trigger": (d.get("trigger") or {}).get("name"),
            "level": d.get("min_level"),
            "item": (d.get("item") or {}).get("name"),
            "held_item": (d.get("held_item") or {}).get("name"),
            "happiness": d.get("min_happiness"),
            "trade_species": (d.get("trade_species") or {}).get("name"),
        })
    return result


def english_text(entries, key):
    for e in entries or []:
        if (e.get("language") or {}).get("name") == "en":
            return re.sub(r"\s+", " ", e.get(key, "")).strip()
    return ""


class PokeAPI:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def get_json(self, url: str, tries: int = 3):
        last = None
        for attempt in range(tries):
            try:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    last = f"HTTP {resp.status}"
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last = f"{type(e).__name__}: {e}"
            await asyncio.sleep(1 + attempt)
        print(f"[PokeAPI] Failed to fetch {url}: {last}")
        return None

    async def species_names(self):
        """{dex number: slug} for every species up to MAX_SPECIES, or None if the API is down."""
        data = await self.get_json(f"{API}/pokemon-species?limit=2000")
        if not data:
            return None
        names = {}
        for entry in data["results"]:
            sid = _id_from_url(entry["url"])
            if 1 <= sid <= MAX_SPECIES:
                names[sid] = entry["name"]
        return names

    async def species_details(self, sid: int):
        """Everything we need about one species, or None on failure."""
        pdata = await self.get_json(f"{API}/pokemon/{sid}")
        sdata = await self.get_json(f"{API}/pokemon-species/{sid}")
        if not pdata or not sdata:
            return None
        evolutions = []
        chain_url = (sdata.get("evolution_chain") or {}).get("url")
        if chain_url:
            chain = await self.get_json(chain_url)
            if chain:
                evolutions = extract_evolutions(chain["chain"], sid)
        evolves_from = sdata.get("evolves_from_species")
        return {
            "id": sid,
            "types": [t["type"]["name"] for t in sorted(pdata["types"], key=lambda t: t["slot"])],
            "base": {API_STAT[s["stat"]["name"]]: s["base_stat"] for s in pdata["stats"] if s["stat"]["name"] in API_STAT},
            "height": pdata.get("height"),  # decimetres
            "weight": pdata.get("weight"),  # hectograms
            "legendary": bool(sdata.get("is_legendary")),
            "mythical": bool(sdata.get("is_mythical")),
            "entry": english_text(sdata.get("flavor_text_entries"), "flavor_text"),
            "genus": english_text(sdata.get("genera"), "genus"),
            "evolves_from": _id_from_url(evolves_from["url"]) if evolves_from else None,
            "evolutions": evolutions,
        }
