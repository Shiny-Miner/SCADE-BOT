"""
Database operations for the Pokémon game.

Every function takes an open sqlite3 connection (`conn`) and is meant to be called
inside `await bot.db.transaction(lambda conn: ...)`, so multi-step changes
(catch + pokédex + coins...) are saved all together or not at all.
"""

import time

from games.pokedata import MAX_LEVEL, STAT_ORDER, xp_needed

START_COINS = 100


# ---------------------------------------------------------------- players
def get_player(conn, user_id):
    return conn.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)).fetchone()


def create_player(conn, user_id):
    conn.execute(
        "INSERT OR IGNORE INTO players (user_id, coins, started_at) VALUES (?, ?, ?)",
        (user_id, START_COINS, int(time.time())),
    )


def add_coins(conn, user_id, amount):
    conn.execute("UPDATE players SET coins = coins + ? WHERE user_id = ?", (amount, user_id))


# ---------------------------------------------------------------- pokémon
def _next_num(conn, user_id) -> int:
    num = conn.execute("SELECT next_num FROM players WHERE user_id = ?", (user_id,)).fetchone()["next_num"]
    conn.execute("UPDATE players SET next_num = next_num + 1 WHERE user_id = ?", (user_id,))
    return num


def add_pokemon(conn, owner_id, species_id, level, ivs, nature, shiny=False, caught=True):
    """
    Give `owner_id` a new pokémon. Returns (pokemon_id, num, first_time_for_dex).
    `caught=True` also counts it in the pokédex / catch statistics.
    """
    now = int(time.time())
    num = _next_num(conn, owner_id)
    cur = conn.execute(
        "INSERT INTO pokemon (owner_id, num, species_id, level, xp, shiny, nature, "
        "iv_hp, iv_atk, iv_def, iv_spa, iv_spd, iv_spe, caught_at, original_owner) "
        "VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (owner_id, num, species_id, level, int(shiny), nature,
         ivs["hp"], ivs["atk"], ivs["def"], ivs["spa"], ivs["spd"], ivs["spe"], now, owner_id),
    )
    first_time = not conn.execute(
        "SELECT 1 FROM pokedex WHERE user_id = ? AND species_id = ?", (owner_id, species_id)
    ).fetchone()
    if caught:
        conn.execute(
            "INSERT INTO pokedex (user_id, species_id, count, first_at) VALUES (?, ?, 1, ?) "
            "ON CONFLICT(user_id, species_id) DO UPDATE SET count = pokedex.count + 1",
            (owner_id, species_id, now),
        )
        conn.execute(
            "UPDATE players SET total_caught = total_caught + 1, shiny_caught = shiny_caught + ? WHERE user_id = ?",
            (int(shiny), owner_id),
        )
    return cur.lastrowid, num, first_time


def register_dex(conn, user_id, species_id):
    """Mark a species as seen (used when a pokémon evolves or is received in a trade)."""
    conn.execute(
        "INSERT OR IGNORE INTO pokedex (user_id, species_id, count, first_at) VALUES (?, ?, 0, ?)",
        (user_id, species_id, int(time.time())),
    )


def get_pokemon_by_num(conn, owner_id, num):
    return conn.execute("SELECT * FROM pokemon WHERE owner_id = ? AND num = ?", (owner_id, num)).fetchone()


def get_pokemon(conn, pokemon_id):
    return conn.execute("SELECT * FROM pokemon WHERE id = ?", (pokemon_id,)).fetchone()


def latest_pokemon(conn, owner_id):
    return conn.execute(
        "SELECT * FROM pokemon WHERE owner_id = ? ORDER BY num DESC LIMIT 1", (owner_id,)
    ).fetchone()


def selected_pokemon(conn, owner_id):
    player = get_player(conn, owner_id)
    if not player or not player["selected"]:
        return None
    return get_pokemon(conn, player["selected"])


def ivs_of(row) -> dict:
    return {k: row[f"iv_{k}"] for k in STAT_ORDER}


def award_xp(conn, pokemon_id, gain):
    """Add XP, handle level-ups. Returns (level_before, level_after, xp_now)."""
    row = conn.execute("SELECT level, xp FROM pokemon WHERE id = ?", (pokemon_id,)).fetchone()
    level, xp = row["level"], row["xp"]
    if level >= MAX_LEVEL:
        return level, level, xp
    before = level
    xp += gain
    while level < MAX_LEVEL and xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
    if level >= MAX_LEVEL:
        xp = 0
    conn.execute("UPDATE pokemon SET level = ?, xp = ? WHERE id = ?", (level, xp, pokemon_id))
    return before, level, xp


def evolve(conn, pokemon_id, owner_id, new_species_id):
    conn.execute("UPDATE pokemon SET species_id = ? WHERE id = ?", (new_species_id, pokemon_id))
    register_dex(conn, owner_id, new_species_id)


def transfer(conn, pokemon_id, new_owner_id):
    """Move a pokémon to another trainer (gets that trainer's next number)."""
    row = get_pokemon(conn, pokemon_id)
    old_owner = row["owner_id"]
    num = _next_num(conn, new_owner_id)
    conn.execute(
        "UPDATE pokemon SET owner_id = ?, num = ?, favorite = 0 WHERE id = ?", (new_owner_id, num, pokemon_id)
    )
    conn.execute("UPDATE players SET selected = NULL WHERE user_id = ? AND selected = ?", (old_owner, pokemon_id))
    conn.execute("DELETE FROM teams WHERE pokemon_id = ?", (pokemon_id,))
    register_dex(conn, new_owner_id, row["species_id"])
    return num


# ------------------------------------------------------------------ items
def item_qty(conn, user_id, item) -> int:
    row = conn.execute("SELECT qty FROM items WHERE user_id = ? AND item = ?", (user_id, item)).fetchone()
    return row["qty"] if row else 0


def add_item(conn, user_id, item, qty):
    conn.execute(
        "INSERT INTO items (user_id, item, qty) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, item) DO UPDATE SET qty = items.qty + excluded.qty",
        (user_id, item, qty),
    )
    conn.execute("DELETE FROM items WHERE user_id = ? AND item = ? AND qty <= 0", (user_id, item))


# ------------------------------------------------------------------- teams
MAX_TEAM = 3


def team_rows(conn, user_id):
    return conn.execute(
        "SELECT p.* FROM teams t JOIN pokemon p ON p.id = t.pokemon_id "
        "WHERE t.user_id = ? AND p.owner_id = ? ORDER BY t.slot",
        (user_id, user_id),
    ).fetchall()


def battle_team(conn, user_id):
    """Your saved team, or just your selected pokémon if you haven't made one."""
    rows = team_rows(conn, user_id)
    if rows:
        return list(rows)
    selected = selected_pokemon(conn, user_id)
    return [selected] if selected else []


def team_add(conn, user_id, pokemon_id):
    slots = conn.execute("SELECT slot, pokemon_id FROM teams WHERE user_id = ?", (user_id,)).fetchall()
    if any(r["pokemon_id"] == pokemon_id for r in slots):
        return "dup"
    if len(slots) >= MAX_TEAM:
        return "full"
    used = {r["slot"] for r in slots}
    slot = next(i for i in range(1, MAX_TEAM + 1) if i not in used)
    conn.execute("INSERT INTO teams (user_id, slot, pokemon_id) VALUES (?, ?, ?)", (user_id, slot, pokemon_id))
    return "ok"


def team_remove(conn, user_id, pokemon_id):
    return conn.execute("DELETE FROM teams WHERE user_id = ? AND pokemon_id = ?", (user_id, pokemon_id)).rowcount


def team_clear(conn, user_id):
    conn.execute("DELETE FROM teams WHERE user_id = ?", (user_id,))


# ------------------------------------------------------------------ battles
WIN_COINS = 60
LOSE_COINS = 15
WIN_XP = 60
BATTLE_DAILY_REWARDS = 10  # rewarded battles per person per day (stops farming with a friend)


def record_battle(conn, user_id, won, today):
    """Update win/loss record and pay coins (if under today's reward limit). Returns (coins, rewarded)."""
    player = get_player(conn, user_id)
    count = player["battle_count"] if player["battle_day"] == today else 0
    rewarded = count < BATTLE_DAILY_REWARDS
    coins = (WIN_COINS if won else LOSE_COINS) if rewarded else 0
    conn.execute(
        "UPDATE players SET battles_won = battles_won + ?, battles_lost = battles_lost + ?, "
        "battle_day = ?, battle_count = ?, coins = coins + ? WHERE user_id = ?",
        (1 if won else 0, 0 if won else 1, today, count + 1, coins, user_id),
    )
    return coins, rewarded


# ------------------------------------------------------------------- market
MARKET_OWNER = 0           # pokémon on sale belong to "nobody" until sold or taken back
MARKET_FEE_PERCENT = 2     # taken from the seller's payout (a coin sink)
MAX_LISTINGS = 20          # per person
MAX_PRICE = 10_000_000


def list_on_market(conn, seller_id, pokemon_id, price):
    conn.execute("UPDATE pokemon SET owner_id = ?, favorite = 0 WHERE id = ?", (MARKET_OWNER, pokemon_id))
    conn.execute("UPDATE players SET selected = NULL WHERE user_id = ? AND selected = ?", (seller_id, pokemon_id))
    conn.execute("DELETE FROM teams WHERE pokemon_id = ?", (pokemon_id,))
    cur = conn.execute(
        "INSERT INTO market (seller_id, pokemon_id, price, listed_at) VALUES (?, ?, ?, ?)",
        (seller_id, pokemon_id, price, int(time.time())),
    )
    return cur.lastrowid


def cancel_listing(conn, seller_id, listing_id):
    """Take your own pokémon back off the market. Returns its new number, or None."""
    listing = conn.execute("SELECT * FROM market WHERE id = ? AND seller_id = ?", (listing_id, seller_id)).fetchone()
    if not listing:
        return None
    conn.execute("DELETE FROM market WHERE id = ?", (listing_id,))
    return transfer(conn, listing["pokemon_id"], seller_id)


def buy_listing(conn, buyer_id, listing_id):
    """Returns ('ok', price, seller_id, pokemon_row) or (error_code,)."""
    listing = conn.execute("SELECT * FROM market WHERE id = ?", (listing_id,)).fetchone()
    if not listing:
        return ("gone",)
    if listing["seller_id"] == buyer_id:
        return ("own",)
    buyer = get_player(conn, buyer_id)
    if buyer["coins"] < listing["price"]:
        return ("poor", listing["price"], buyer["coins"])
    fee = listing["price"] * MARKET_FEE_PERCENT // 100
    add_coins(conn, buyer_id, -listing["price"])
    add_coins(conn, listing["seller_id"], listing["price"] - fee)
    conn.execute("DELETE FROM market WHERE id = ?", (listing_id,))
    transfer(conn, listing["pokemon_id"], buyer_id)
    return ("ok", listing["price"], listing["seller_id"], get_pokemon(conn, listing["pokemon_id"]))
