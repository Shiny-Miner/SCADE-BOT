"""
SCADE Pokémon: a Pokétwo-style game.

Wild pokémon spawn while people chat -> guess the name with !catch -> build a collection,
level up your selected pokémon by chatting, evolve them, fill the pokédex, hunt shinies,
trade, earn coins and buy items. Everything is stored in the SQLite database.
"""

import asyncio
import json
import math
import random
import time
import traceback
from dataclasses import dataclass, field

import aiohttp
import discord
from discord.ext import commands, tasks

from games import pokestore as ps
from games.pokedata import (
    MAX_LEVEL,
    MAX_SPECIES,
    STAT_LABEL,
    STAT_ORDER,
    STARTER_IDS,
    STARTERS,
    TYPE_COLORS,
    LEGENDARY,
    MYTHICAL,
    PokeAPI,
    ULTRA_BEASTS,
    accepted_guesses,
    artwork_url,
    calc_stats,
    hint_reveal_count,
    item_evolution,
    iv_percent,
    level_evolution,
    make_hint,
    norm,
    pick_species,
    pretty_name,
    random_ivs,
    random_nature,
    rarity_of,
    shiny_chance,
    trade_evolution,
    xp_needed,
)

PREFIX = "!"
PER_PAGE = 15
DEX_PER_PAGE = 25
XP_COOLDOWN = 15  # seconds between XP gains per person
DAILY_COOLDOWN = 20 * 3600
INCENSE_SECONDS = 30 * 60

SHOP = {
    "rarecandy": {
        "name": "Rare Candy", "emoji": "🍬", "price": 400,
        "desc": "Instantly raises your selected pokémon by 1 level.",
    },
    "incense": {
        "name": "Spawn Incense", "emoji": "🕯️", "price": 750,
        "desc": "Pokémon appear rapidly in the channel you use it in for 30 minutes.",
    },
}

STONES = ["fire", "water", "thunder", "leaf", "moon", "sun", "shiny", "dusk", "dawn", "ice"]
for _stone in STONES:
    SHOP[f"{_stone}-stone"] = {
        "name": f"{_stone.title()} Stone", "emoji": "💎", "price": 900, "evo_item": f"{_stone}-stone",
        "desc": f"Evolves your selected pokémon if it evolves with a {_stone.title()} Stone.",
    }

SORTS = {
    "num": "num ASC",
    "recent": "num DESC",
    "iv": "(iv_hp + iv_atk + iv_def + iv_spa + iv_spd + iv_spe) DESC, num ASC",
    "level": "level DESC, num ASC",
    "dex": "species_id ASC, num ASC",
}

LEADERBOARDS = {
    "catches": ("total_caught", "🏆 Most pokémon caught"),
    "shinies": ("shiny_caught", "✨ Most shiny pokémon"),
    "coins": ("coins", "💰 Richest trainers"),
    "pokedex": (None, "📖 Biggest pokédex"),
    "battles": ("battles_won", "⚔️ Most battles won"),
}


@dataclass
class Spawn:
    species_id: int
    name: str
    accepted: set
    level: int
    hint_order: list = field(default_factory=list)
    reveal: int = 1


# ============================================================ small UI helpers
class Paginator(discord.ui.View):
    """◀ ▶ buttons for any list. `fetch(page_index)` must return an Embed."""

    def __init__(self, author_id, total_pages, fetch, page=0):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.total = max(1, total_pages)
        self.fetch = fetch
        self.page = page
        self.message = None
        self._sync()

    def _sync(self):
        self.btn_first.disabled = self.btn_prev.disabled = self.page <= 0
        self.btn_next.disabled = self.btn_last.disabled = self.page >= self.total - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This list belongs to someone else. Run the command yourself 😉", ephemeral=True)
            return False
        return True

    async def _go(self, interaction, page):
        self.page = max(0, min(self.total - 1, page))
        self._sync()
        embed = await self.fetch(self.page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def btn_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, 0)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, self.page - 1)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, self.page + 1)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def btn_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, self.total - 1)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class ConfirmView(discord.ui.View):
    """Two buttons. `await view.wait()` then read `view.value` (True / False / None=timed out)."""

    def __init__(self, user_ids, yes_label="Confirm", no_label="Cancel", timeout=60):
        super().__init__(timeout=timeout)
        self.user_ids = set(user_ids)
        self.value = None
        yes = discord.ui.Button(label=yes_label, style=discord.ButtonStyle.success)
        no = discord.ui.Button(label=no_label, style=discord.ButtonStyle.danger)
        yes.callback = self._yes
        no.callback = self._no
        self.add_item(yes)
        self.add_item(no)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.user_ids:
            await interaction.response.send_message("These buttons aren't for you 😉", ephemeral=True)
            return False
        return True

    async def _yes(self, interaction: discord.Interaction):
        self.value = True
        await interaction.response.defer()
        self.stop()

    async def _no(self, interaction: discord.Interaction):
        self.value = False
        await interaction.response.defer()
        self.stop()


def split_item_amount(text: str):
    """'rare candy 3' -> ('rare candy', 3)"""
    tokens = text.split()
    amount = 1
    if tokens and tokens[-1].isdigit():
        amount = int(tokens.pop())
    return " ".join(tokens), amount


def find_item(text: str):
    n = norm(text)
    if n in ("candy", "rarecandies", "candies"):
        return "rarecandy"
    for key, item in SHOP.items():
        if n in (key, norm(item["name"])):
            return key
    return None


def mention_only(user):
    return discord.AllowedMentions(users=[user], roles=False, everyone=False)


# ===================================================================== the cog
class Pokemon(commands.Cog):
    """Catch, collect, level up, evolve, trade."""

    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.api = None
        self.names = {}        # dex number -> slug
        self.name_index = {}   # normalised name -> dex number
        self.species_cache = {}
        self.spawns = {}       # channel_id -> Spawn
        self.spawn_locks = {}  # channel_id -> asyncio.Lock
        self.counters = {}     # guild_id -> [messages so far, messages needed]
        self.last_spawn = {}   # guild_id -> time
        self.xp_cooldown = {}  # user_id -> time
        self.spawn_cfg = {}    # guild_id -> [channel ids]
        self.incense_next = {}  # channel_id -> time
        self._names_task = None

    # ----------------------------------------------------------- lifecycle
    async def cog_load(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15), headers={"User-Agent": "SCADE-Discord-Bot"}
        )
        self.api = PokeAPI(self.session)
        await self._load_names_from_db()
        self._names_task = asyncio.create_task(self._refresh_names())
        self.incense_loop.start()

    async def cog_unload(self):
        self.incense_loop.cancel()
        if self._names_task:
            self._names_task.cancel()
        if self.session:
            await self.session.close()

    # ---------------------------------------------------------------- names
    def _set_names(self, names: dict):
        self.names = names
        self.name_index = {}
        for sid, slug in names.items():
            self.name_index[norm(slug)] = sid
            self.name_index[norm(pretty_name(slug))] = sid

    async def _load_names_from_db(self):
        rows = await self.bot.db.fetchall("SELECT id, name FROM species_names")
        if rows:
            self._set_names({r["id"]: r["name"] for r in rows})

    async def _refresh_names(self):
        """Download the species list once (and again monthly). Retries if PokéAPI is down."""
        try:
            last = int(await self.bot.db.meta_get("names_fetched_at", 0) or 0)
            if len(self.names) >= 1000 and time.time() - last < 30 * 86400:
                return
            delay = 30
            while True:
                names = await self.api.species_names()
                if names and len(names) >= 1000:
                    def work(conn):
                        conn.execute("DELETE FROM species_names")
                        conn.executemany("INSERT INTO species_names (id, name) VALUES (?, ?)", list(names.items()))

                    await self.bot.db.transaction(work)
                    await self.bot.db.meta_set("names_fetched_at", int(time.time()))
                    self._set_names(names)
                    print(f"[Pokemon] Loaded {len(names)} species names.")
                    return
                if self.names:
                    return  # PokéAPI is down but we already have a saved list
                print(f"[Pokemon] Couldn't load species names; retrying in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 600)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def label(self, species_id: int) -> str:
        slug = self.names.get(species_id)
        return pretty_name(slug) if slug else f"Pokémon #{species_id}"

    def display_name(self, row) -> str:
        return row["nickname"] or self.label(row["species_id"])

    def lookup_species(self, text: str):
        text = text.strip()
        if text.isdigit() and 1 <= int(text) <= MAX_SPECIES:
            return int(text)
        return self.name_index.get(norm(text))

    async def get_species(self, species_id: int):
        """Details (types, base stats, evolutions...). Cached forever in the database."""
        if species_id in self.species_cache:
            return self.species_cache[species_id]
        row = await self.bot.db.fetchone("SELECT data FROM species_data WHERE id = ?", (species_id,))
        if row:
            data = json.loads(row["data"])
        else:
            data = await self.api.species_details(species_id)
            if not data:
                return None
            await self.bot.db.execute(
                "INSERT OR REPLACE INTO species_data (id, data, fetched_at) VALUES (?, ?, ?)",
                (species_id, json.dumps(data), int(time.time())),
            )
        self.species_cache[species_id] = data
        return data

    # ------------------------------------------------------------- helpers
    async def require_player(self, ctx):
        row = await self.bot.db.fetchone("SELECT * FROM players WHERE user_id = ?", (ctx.author.id,))
        if not row:
            await ctx.send(f"👋 You haven't started yet! Use `{PREFIX}start` to pick your starter pokémon.")
        return row

    async def spawn_channels(self, guild_id: int):
        if guild_id not in self.spawn_cfg:
            row = await self.bot.db.fetchone("SELECT spawn_channels FROM guild_settings WHERE guild_id = ?", (guild_id,))
            self.spawn_cfg[guild_id] = json.loads(row["spawn_channels"]) if row else []
        return self.spawn_cfg[guild_id]

    def embed_color(self, species):
        if species and species.get("types"):
            return discord.Color(TYPE_COLORS.get(species["types"][0], 0x5865F2))
        return discord.Color.blurple()

    async def pokemon_embed(self, row, title_prefix=""):
        species = await self.get_species(row["species_id"])
        ivs = ps.ivs_of(row)
        name = self.label(row["species_id"])
        shiny = bool(row["shiny"])
        title = f"{'✨ ' if shiny else ''}{title_prefix}Level {row['level']} {name}"
        if row["nickname"]:
            title += f' "{row["nickname"]}"'
        if row["favorite"]:
            title += " ⭐"

        xp_line = "MAX" if row["level"] >= MAX_LEVEL else f"{row['xp']}/{xp_needed(row['level'])}"
        lines = [f"**XP:** {xp_line}", f"**Nature:** {row['nature']}"]
        if species:
            lines.append("**Types:** " + " / ".join(t.title() for t in species["types"]))
        rarity = rarity_of(row["species_id"])
        if rarity != "Common":
            lines.append(f"**Rarity:** {rarity}")
        if row["caught_at"]:
            lines.append(f"**Caught:** <t:{row['caught_at']}:R>")

        embed = discord.Embed(title=title, description="\n".join(lines), color=self.embed_color(species))
        if species:
            stats = calc_stats(species["base"], ivs, row["level"], row["nature"])
            stat_lines = [f"**{STAT_LABEL[k]}:** {stats[k]} – IV: {ivs[k]}/31" for k in STAT_ORDER]
        else:
            stat_lines = [f"**{STAT_LABEL[k]}:** IV {ivs[k]}/31" for k in STAT_ORDER]
        stat_lines.append(f"**Total IV:** {iv_percent(ivs)}%")
        embed.add_field(name="Stats", value="\n".join(stat_lines), inline=False)
        embed.set_image(url=artwork_url(row["species_id"], shiny))
        embed.set_footer(text=f"Displaying pokémon: {row['num']}")
        return embed

    # --------------------------------------------------------------- spawns
    async def spawn(self, channel, species_id=None) -> bool:
        if not self.names:
            return False
        sid = species_id or pick_species(self.names.keys())
        name = self.label(sid)
        letters = [i for i, c in enumerate(name) if c.isalpha()]
        spawn = Spawn(
            species_id=sid,
            name=name,
            accepted=accepted_guesses(self.names[sid]),
            level=random.randint(1, 35),
            hint_order=random.sample(letters, len(letters)),
            reveal=hint_reveal_count(name),
        )
        embed = discord.Embed(
            title="A wild pokémon has appeared!",
            description=f"Guess the pokémon and type `{PREFIX}catch <pokémon>` to catch it!",
            color=discord.Color.gold(),
        )
        embed.set_image(url=artwork_url(sid))
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            print(f"[Pokemon] Couldn't spawn in #{channel}: {e}")
            return False
        self.spawns[channel.id] = spawn  # any older spawn in this channel flees
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild or not message.content:
            return
        if message.content.startswith(PREFIX):
            return  # commands don't count
        try:
            await self.award_chat_xp(message)
            await self.count_for_spawn(message)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    async def count_for_spawn(self, message):
        if not self.names:
            return
        gid = message.guild.id
        counter = self.counters.setdefault(gid, [0, random.randint(25, 45)])
        counter[0] += 1
        if counter[0] < counter[1]:
            return
        now = time.time()
        if now - self.last_spawn.get(gid, 0) < 20:
            return
        counter[0], counter[1] = 0, random.randint(25, 45)
        self.last_spawn[gid] = now

        me = message.guild.me
        target = message.channel
        configured = await self.spawn_channels(gid)
        if configured:
            options = [
                ch for ch in (message.guild.get_channel(i) for i in configured)
                if ch and ch.permissions_for(me).send_messages
            ]
            if options:
                target = random.choice(options)
        if target.permissions_for(me).send_messages:
            await self.spawn(target)

    async def award_chat_xp(self, message):
        uid = message.author.id
        now = time.time()
        if now - self.xp_cooldown.get(uid, 0) < XP_COOLDOWN:
            return
        self.xp_cooldown[uid] = now

        def work(conn):
            player = ps.get_player(conn, uid)
            if not player or not player["selected"]:
                return None
            before, after, _ = ps.award_xp(conn, player["selected"], random.randint(12, 28))
            return before, after, dict(ps.get_pokemon(conn, player["selected"])), bool(player["silenced"])

        result = await self.bot.db.transaction(work)
        if not result:
            return
        before, after, row, silenced = result
        if after > before:
            await self.announce_level(message.channel, message.author, row, after, silenced)

    async def try_evolve(self, row, level):
        """Level-based evolution. Returns the new species id, or None."""
        species = await self.get_species(row["species_id"])
        if not species:
            return None
        evo = level_evolution(species["evolutions"], level)
        if not evo:
            return None
        await self.bot.db.transaction(lambda conn: ps.evolve(conn, row["id"], row["owner_id"], evo["to"]))
        return evo["to"]

    async def announce_level(self, channel, user, row, level, silenced):
        old_label = self.display_name(row)
        new_species = await self.try_evolve(row, level)
        try:
            if new_species:
                embed = discord.Embed(
                    title="🌟 Your pokémon is evolving!",
                    description=f"Congratulations {user.mention}! Your **{old_label}** is now level {level} and evolved into **{self.label(new_species)}**!",
                    color=discord.Color.gold(),
                )
                embed.set_thumbnail(url=artwork_url(new_species, bool(row["shiny"])))
                await channel.send(embed=embed, allowed_mentions=mention_only(user))
            elif not silenced:
                await channel.send(
                    f"🎉 Congratulations {user.mention}! Your **{old_label}** is now level **{level}**!",
                    allowed_mentions=mention_only(user),
                )
        except discord.HTTPException:
            pass

    @tasks.loop(seconds=20)
    async def incense_loop(self):
        try:
            now = int(time.time())
            for row in await self.bot.db.fetchall("SELECT * FROM incense"):
                cid = row["channel_id"]
                channel = self.bot.get_channel(cid)
                if row["expires_at"] <= now:
                    await self.bot.db.execute("DELETE FROM incense WHERE channel_id = ?", (cid,))
                    self.incense_next.pop(cid, None)
                    if channel:
                        try:
                            await channel.send("🕯️ The incense burned out.")
                        except discord.HTTPException:
                            pass
                elif channel and time.time() >= self.incense_next.get(cid, 0):
                    self.incense_next[cid] = time.time() + random.randint(25, 50)
                    await self.spawn(channel)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    @incense_loop.before_loop
    async def before_incense(self):
        await self.bot.wait_until_ready()

    # ============================================================ commands: start
    @commands.command(name="start", help="Begin your pokémon journey.")
    async def start(self, ctx):
        if await self.bot.db.fetchone("SELECT 1 FROM players WHERE user_id = ?", (ctx.author.id,)):
            return await ctx.send(f"You already have a starter! Use `{PREFIX}pokemon` to see your collection.")
        embed = discord.Embed(
            title="⚡ Welcome to the world of pokémon!",
            description=f"Pick your starter with `{PREFIX}pick <pokémon>`, for example `{PREFIX}pick bulbasaur`.",
            color=discord.Color.gold(),
        )
        for region, starters in STARTERS.items():
            embed.add_field(name=region, value=" • ".join(pretty_name(s) for s in starters), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="pick", usage="<starter>", help="Choose your starter pokémon.")
    async def pick(self, ctx, *, name: str):
        key = next((s for s in STARTER_IDS if norm(s) == norm(name)), None)
        if not key:
            return await ctx.send(f"❌ That's not a starter pokémon. See the list with `{PREFIX}start`.")
        species_id = STARTER_IDS[key]
        uid = ctx.author.id

        def work(conn):
            if ps.get_player(conn, uid):
                return None
            ps.create_player(conn, uid)
            pid, num, _ = ps.add_pokemon(conn, uid, species_id, 5, random_ivs(), random_nature(), False)
            conn.execute("UPDATE players SET selected = ? WHERE user_id = ?", (pid, uid))
            return pid

        pid = await self.bot.db.transaction(work)
        if pid is None:
            return await ctx.send("You've already picked a starter!")
        row = await self.bot.db.fetchone("SELECT * FROM pokemon WHERE id = ?", (pid,))
        embed = await self.pokemon_embed(row, "Your starter: ")
        embed.add_field(
            name="Welcome!",
            value=f"It's selected, so it levels up as you chat. You also got **{ps.START_COINS} 🪙**. Try `{PREFIX}help` for everything you can do!",
            inline=False,
        )
        await ctx.send(embed=embed)
        self.bot.dispatch("scade_data_changed")

    # =========================================================== commands: catch
    @commands.command(name="catch", aliases=["c"], usage="<pokémon name>", help="Catch the wild pokémon.")
    @commands.guild_only()
    async def catch(self, ctx, *, guess: str):
        player = await self.require_player(ctx)
        if not player:
            return
        lock = self.spawn_locks.setdefault(ctx.channel.id, asyncio.Lock())
        async with lock:
            spawn = self.spawns.get(ctx.channel.id)
            if spawn is None:
                return await ctx.send("❌ There's no wild pokémon here right now.")
            if norm(guess) not in spawn.accepted:
                return await ctx.send("That is the wrong pokémon!")
            del self.spawns[ctx.channel.id]

        uid = ctx.author.id

        def work(conn):
            hunt = conn.execute("SELECT * FROM shiny_hunt WHERE user_id = ?", (uid,)).fetchone()
            hunting = bool(hunt and hunt["species_id"] == spawn.species_id)
            shiny = random.random() < shiny_chance(hunt["streak"] if hunting else 0)
            ivs, nature = random_ivs(), random_nature()
            pid, num, first = ps.add_pokemon(conn, uid, spawn.species_id, spawn.level, ivs, nature, shiny)
            if hunting:
                if shiny:
                    conn.execute("DELETE FROM shiny_hunt WHERE user_id = ?", (uid,))
                else:
                    conn.execute("UPDATE shiny_hunt SET streak = streak + 1 WHERE user_id = ?", (uid,))
            coins = random.randint(15, 40) + (25 if first else 0) + (500 if shiny else 0)
            ps.add_coins(conn, uid, coins)
            return num, first, shiny, ivs, coins

        num, first, shiny, ivs, coins = await self.bot.db.transaction(work)
        text = (
            f"Congratulations {ctx.author.mention}! You caught a Level {spawn.level} "
            f"**{spawn.name}** ({iv_percent(ivs)}%)! Pokémon #{num}"
        )
        extras = []
        if first:
            extras.append("Added to the Pokédex!")
        if shiny:
            extras.append("✨ **This is a shiny pokémon!** ✨")
        extras.append(f"+{coins} 🪙")
        await ctx.send(text + "\n" + " ".join(extras), allowed_mentions=mention_only(ctx.author))

    @commands.command(name="hint", help="Get a hint for the wild pokémon.")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def hint(self, ctx):
        spawn = self.spawns.get(ctx.channel.id)
        if not spawn:
            return await ctx.send("❌ There's no wild pokémon to give a hint about right now!")
        await ctx.send(f"The pokémon is {make_hint(spawn.name, spawn.hint_order, spawn.reveal)}")

    # ======================================================= commands: collection
    def _parse_list_args(self, text):
        flags = {"page": 1, "shiny": False, "fav": False, "sort": "num", "name": None, "rarity": None}
        for token in (text or "").split():
            low = token.lower()
            if low.isdigit():
                flags["page"] = max(1, int(low))
            elif low == "shiny":
                flags["shiny"] = True
            elif low in ("fav", "favorite", "favorites", "favourite", "favourites"):
                flags["fav"] = True
            elif low in ("legendary", "mythical", "ub"):
                flags["rarity"] = low
            elif low.startswith("sort:") and low[5:] in SORTS:
                flags["sort"] = low[5:]
            elif low.startswith("name:") and len(low) > 5:
                flags["name"] = token[5:]
            else:
                return None
        return flags

    def _list_where(self, owner_id, flags):
        where, params = ["owner_id = ?"], [owner_id]
        if flags["shiny"]:
            where.append("shiny = 1")
        if flags["fav"]:
            where.append("favorite = 1")
        if flags["rarity"]:
            group = {"legendary": LEGENDARY, "mythical": MYTHICAL, "ub": ULTRA_BEASTS}[flags["rarity"]]
            where.append("species_id IN (" + ",".join(str(int(i)) for i in sorted(group)) + ")")
        if flags["name"]:
            q = norm(flags["name"])
            ids = [sid for sid, slug in self.names.items() if q in norm(slug) or q in norm(pretty_name(slug))][:300]
            like = "%" + flags["name"].lower().replace("%", "") + "%"
            if ids:
                where.append(f"(species_id IN ({','.join('?' * len(ids))}) OR LOWER(COALESCE(nickname, '')) LIKE ?)")
                params += ids + [like]
            else:
                where.append("LOWER(COALESCE(nickname, '')) LIKE ?")
                params.append(like)
        return " AND ".join(where), params

    def _list_line(self, row):
        ivs = ps.ivs_of(row)
        name = self.label(row["species_id"])
        if row["nickname"]:
            name = f"{row['nickname']} ({name})"
        marks = ("⭐ " if row["favorite"] else "") + ("✨ " if row["shiny"] else "")
        return f"`{row['num']:>4}`  {marks}**{name}** • Lvl. {row['level']} • IV: {iv_percent(ivs)}%"

    @commands.command(
        name="pokemon", aliases=["pk", "pokes"], usage="[page] [shiny] [fav] [legendary|mythical|ub] [sort:iv|level|dex|recent|num] [name:pika]",
        help="Show your pokémon collection.",
    )
    async def pokemon_list(self, ctx, *, options: str = None):
        if not await self.require_player(ctx):
            return
        flags = self._parse_list_args(options)
        if flags is None:
            return await ctx.send(
                f"❌ I didn't understand that. Try `{PREFIX}pokemon 2`, `{PREFIX}pokemon shiny`, "
                f"`{PREFIX}pokemon sort:iv` or `{PREFIX}pokemon name:pikachu`."
            )
        where, params = self._list_where(ctx.author.id, flags)
        total = (await self.bot.db.fetchone(f"SELECT COUNT(*) AS n FROM pokemon WHERE {where}", params))["n"]
        if total == 0:
            return await ctx.send("You don't have any pokémon matching that. Wait for a wild one and `!catch` it!")
        pages = math.ceil(total / PER_PAGE)
        order = SORTS[flags["sort"]]

        async def fetch(index):
            rows = await self.bot.db.fetchall(
                f"SELECT * FROM pokemon WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [PER_PAGE, index * PER_PAGE],
            )
            first = index * PER_PAGE + 1
            embed = discord.Embed(
                title=f"{ctx.author.display_name}'s pokémon",
                description="\n".join(self._list_line(r) for r in rows),
                color=discord.Color.blurple(),
            )
            embed.set_footer(text=f"Showing {first}–{first + len(rows) - 1} of {total} • Page {index + 1}/{pages}")
            return embed

        page = min(flags["page"], pages) - 1
        embed = await fetch(page)
        if pages == 1:
            return await ctx.send(embed=embed)
        view = Paginator(ctx.author.id, pages, fetch, page)
        view.message = await ctx.send(embed=embed, view=view)

    def _resolve(self, conn, owner_id, which):
        """'', 'latest' or a number -> pokémon row (or None)."""
        if which is None or which == "":
            return ps.selected_pokemon(conn, owner_id)
        low = which.lower()
        if low in ("latest", "l", "last"):
            return ps.latest_pokemon(conn, owner_id)
        if low.isdigit():
            return ps.get_pokemon_by_num(conn, owner_id, int(low))
        return False  # not understood

    @commands.command(name="info", aliases=["i"], usage="[number | latest]", help="Show details about one of your pokémon.")
    async def info(self, ctx, *, which: str = None):
        if not await self.require_player(ctx):
            return
        row = await self.bot.db.run(lambda conn: self._resolve(conn, ctx.author.id, which))
        if row is False:
            return await ctx.send(f"❌ Use a pokémon number or `latest`, e.g. `{PREFIX}info 12`.")
        if not row:
            return await ctx.send("❌ I couldn't find that pokémon. Select one with `!select <number>`.")
        await ctx.send(embed=await self.pokemon_embed(row))

    @commands.command(name="select", aliases=["sel"], usage="<number>", help="Choose which pokémon gains XP from your chatting.")
    async def select(self, ctx, number: int):
        if not await self.require_player(ctx):
            return

        def work(conn):
            row = ps.get_pokemon_by_num(conn, ctx.author.id, number)
            if row:
                conn.execute("UPDATE players SET selected = ? WHERE user_id = ?", (row["id"], ctx.author.id))
            return row

        row = await self.bot.db.transaction(work)
        if not row:
            return await ctx.send("❌ You don't have a pokémon with that number.")
        await ctx.send(f"✅ You selected your level {row['level']} **{self.label(row['species_id'])}** (#{number}).")

    @commands.command(name="nickname", aliases=["nick"], usage="[number] <nickname | reset>", help="Give a pokémon a nickname.")
    async def nickname(self, ctx, *, text: str):
        if not await self.require_player(ctx):
            return
        parts = text.split(maxsplit=1)
        number = None
        if len(parts) == 2 and parts[0].isdigit():
            number, text = int(parts[0]), parts[1]
        nick = None if text.strip().lower() == "reset" else text.strip().replace("@", "").replace("<", "").replace(">", "")[:20]
        if nick is not None and not nick:
            return await ctx.send("❌ That nickname isn't allowed.")

        def work(conn):
            row = ps.get_pokemon_by_num(conn, ctx.author.id, number) if number else ps.selected_pokemon(conn, ctx.author.id)
            if row:
                conn.execute("UPDATE pokemon SET nickname = ? WHERE id = ?", (nick, row["id"]))
            return row

        row = await self.bot.db.transaction(work)
        if not row:
            return await ctx.send("❌ I couldn't find that pokémon.")
        name = self.label(row["species_id"])
        msg = f"✅ Reset the nickname of your **{name}**." if nick is None else f"✅ Your **{name}** is now called **{nick}**."
        await ctx.send(msg, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="favorite", aliases=["fav"], usage="[number]", help="Star a pokémon so it can't be released or traded.")
    async def favorite(self, ctx, number: int = None):
        if not await self.require_player(ctx):
            return

        def work(conn):
            row = ps.get_pokemon_by_num(conn, ctx.author.id, number) if number else ps.selected_pokemon(conn, ctx.author.id)
            if not row:
                return None
            new = 0 if row["favorite"] else 1
            conn.execute("UPDATE pokemon SET favorite = ? WHERE id = ?", (new, row["id"]))
            return row, new

        res = await self.bot.db.transaction(work)
        if not res:
            return await ctx.send("❌ I couldn't find that pokémon.")
        row, new = res
        await ctx.send(f"{'⭐ Favorited' if new else '✅ Unfavorited'} your **{self.label(row['species_id'])}** (#{row['num']}).")

    @commands.command(name="release", aliases=["rel"], usage="<number> [number ...]", help="Release pokémon for coins.")
    async def release(self, ctx, numbers: commands.Greedy[int]):
        if not await self.require_player(ctx):
            return
        numbers = list(dict.fromkeys(numbers))[:25]
        if not numbers:
            return await ctx.send(f"❌ Tell me which pokémon: `{PREFIX}release 12 15 20`.")

        def look(conn):
            player = ps.get_player(conn, ctx.author.id)
            rows = [ps.get_pokemon_by_num(conn, ctx.author.id, n) for n in numbers]
            return player["selected"], rows

        selected, rows = await self.bot.db.run(look)
        if any(r is None for r in rows):
            return await ctx.send("❌ You don't own one of those numbers.")
        for r in rows:
            if r["favorite"]:
                return await ctx.send(f"❌ #{r['num']} is a favorite. Unfavorite it first.")
            if r["id"] == selected:
                return await ctx.send(f"❌ #{r['num']} is your selected pokémon. Select another one first.")
        ids = [r["id"] for r in rows]
        reward = sum(5 + r["level"] for r in rows)
        listing = "\n".join(f"#{r['num']} {self.label(r['species_id'])} (Lvl {r['level']}, {iv_percent(ps.ivs_of(r))}%)" for r in rows)
        view = ConfirmView({ctx.author.id}, "Release", "Cancel", timeout=45)
        msg = await ctx.send(f"⚠️ Release these {len(rows)} pokémon for **{reward} 🪙**? This can't be undone.\n{listing}"[:1990], view=view)
        await view.wait()

        if not view.value:
            return await msg.edit(content="Release cancelled.", view=None)

        def do(conn):
            placeholders = ",".join("?" * len(ids))
            check = conn.execute(
                f"SELECT COUNT(*) AS n FROM pokemon WHERE owner_id = ? AND favorite = 0 AND id IN ({placeholders})",
                [ctx.author.id] + ids,
            ).fetchone()["n"]
            if check != len(ids):
                return False
            conn.execute(f"DELETE FROM teams WHERE pokemon_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM pokemon WHERE id IN ({placeholders})", ids)
            conn.execute("UPDATE players SET selected = NULL WHERE user_id = ? AND selected IN (" + placeholders + ")", [ctx.author.id] + ids)
            ps.add_coins(conn, ctx.author.id, reward)
            return True

        ok = await self.bot.db.transaction(do)
        await msg.edit(content=f"✅ Released {len(ids)} pokémon and got **{reward} 🪙**." if ok else "❌ Something changed, nothing was released.", view=None)

    # ---------------------------------------------------------------- pokédex
    def _evolution_text(self, species):
        parts = []
        if species.get("evolves_from"):
            parts.append(f"Evolves from **{self.label(species['evolves_from'])}**")
        for evo in species.get("evolutions", []):
            if evo.get("trigger") == "level-up" and evo.get("level"):
                how = f"Lv. {evo['level']}"
            elif evo.get("item"):
                how = evo["item"].replace("-", " ").title()
            else:
                how = (evo.get("trigger") or "special").replace("-", " ").title()
            parts.append(f"Evolves into **{self.label(evo['to'])}** ({how})")
        return "\n".join(parts) or "Does not evolve."

    @commands.command(name="pokedex", aliases=["dex", "d"], usage="[pokémon name | number]", help="See pokédex progress, or info about a species.")
    async def pokedex(self, ctx, *, query: str = None):
        if not self.names:
            return await ctx.send("⏳ I'm still loading the pokédex data. Try again in a minute!")

        if query:
            sid = self.lookup_species(query)
            if not sid:
                return await ctx.send("❌ I don't know a pokémon with that name or number.")
            species = await self.get_species(sid)
            embed = discord.Embed(
                title=f"#{sid:03d} — {self.label(sid)}",
                description=(species or {}).get("entry") or "No pokédex entry available right now.",
                color=self.embed_color(species),
            )
            if species:
                embed.add_field(name="Types", value=" / ".join(t.title() for t in species["types"]), inline=True)
                if species.get("genus"):
                    embed.add_field(name="Species", value=species["genus"], inline=True)
                if species.get("height") is not None:
                    embed.add_field(name="Size", value=f"{species['height'] / 10:.1f} m • {species['weight'] / 10:.1f} kg", inline=True)
                embed.add_field(
                    name="Base stats",
                    value="\n".join(f"**{STAT_LABEL[k]}:** {species['base'].get(k, '?')}" for k in STAT_ORDER),
                    inline=True,
                )
                embed.add_field(name="Evolution", value=self._evolution_text(species), inline=True)
            rarity = rarity_of(sid)
            if rarity != "Common":
                embed.add_field(name="Rarity", value=rarity, inline=True)
            player = await self.bot.db.fetchone(
                "SELECT count FROM pokedex WHERE user_id = ? AND species_id = ?", (ctx.author.id, sid)
            )
            if player:
                embed.set_footer(text=f"You've caught {player['count']} of these")
            else:
                embed.set_footer(text="You haven't caught this one yet")
            embed.set_image(url=artwork_url(sid))
            return await ctx.send(embed=embed)

        if not await self.require_player(ctx):
            return
        rows = await self.bot.db.fetchall("SELECT species_id, count FROM pokedex WHERE user_id = ?", (ctx.author.id,))
        caught = {r["species_id"]: r["count"] for r in rows}
        total = max(self.names)
        pages = math.ceil(total / DEX_PER_PAGE)

        async def fetch(index):
            start = index * DEX_PER_PAGE + 1
            lines = []
            for sid in range(start, min(start + DEX_PER_PAGE, total + 1)):
                if sid in caught:
                    lines.append(f"✅ `#{sid:03d}` {self.label(sid)} ×{caught[sid]}")
                else:
                    lines.append(f"▫️ `#{sid:03d}` {self.label(sid)}")
            embed = discord.Embed(
                title=f"{ctx.author.display_name}'s pokédex",
                description=f"**Registered: {len(caught)}/{total}**\n\n" + "\n".join(lines),
                color=discord.Color.red(),
            )
            embed.set_footer(text=f"Page {index + 1}/{pages} • {PREFIX}dex <name> for details on one pokémon")
            return embed

        view = Paginator(ctx.author.id, pages, fetch, 0)
        view.message = await ctx.send(embed=await fetch(0), view=view)

    @commands.command(name="shinyhunt", aliases=["sh"], usage="[pokémon | off]", help="Hunt a shiny: every catch of it boosts your odds.")
    async def shinyhunt(self, ctx, *, query: str = None):
        if not await self.require_player(ctx):
            return
        hunt = await self.bot.db.fetchone("SELECT * FROM shiny_hunt WHERE user_id = ?", (ctx.author.id,))
        if not query:
            if not hunt:
                return await ctx.send(f"You aren't hunting anything. Start with `{PREFIX}shinyhunt <pokémon>`.")
            odds = round(1 / shiny_chance(hunt["streak"]))
            return await ctx.send(f"✨ Hunting **{self.label(hunt['species_id'])}**: streak **{hunt['streak']}**, shiny odds **1/{odds}**.")
        if query.strip().lower() in ("off", "stop", "none", "clear"):
            await self.bot.db.execute("DELETE FROM shiny_hunt WHERE user_id = ?", (ctx.author.id,))
            return await ctx.send("✅ Shiny hunt stopped.")
        sid = self.lookup_species(query)
        if not sid:
            return await ctx.send("❌ I don't know a pokémon with that name.")
        await self.bot.db.execute(
            "INSERT INTO shiny_hunt (user_id, species_id, streak) VALUES (?, ?, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET species_id = excluded.species_id, "
            "streak = CASE WHEN shiny_hunt.species_id = excluded.species_id THEN shiny_hunt.streak ELSE 0 END",
            (ctx.author.id, sid),
        )
        await ctx.send(f"✨ You're now hunting **{self.label(sid)}**! Every one you catch raises your shiny odds.")

    @commands.command(name="silence", help="Toggle level-up messages for yourself.")
    async def silence(self, ctx):
        if not await self.require_player(ctx):
            return
        await self.bot.db.execute("UPDATE players SET silenced = 1 - silenced WHERE user_id = ?", (ctx.author.id,))
        row = await self.bot.db.fetchone("SELECT silenced FROM players WHERE user_id = ?", (ctx.author.id,))
        await ctx.send("🔕 Level-up messages are now **off** for you." if row["silenced"] else "🔔 Level-up messages are now **on** for you.")

    # ========================================================== commands: economy
    @commands.command(name="balance", aliases=["bal", "profile"], help="Show your coins and stats.")
    async def balance(self, ctx):
        player = await self.require_player(ctx)
        if not player:
            return
        dex = (await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM pokedex WHERE user_id = ?", (ctx.author.id,)))["n"]
        owned = (await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM pokemon WHERE owner_id = ?", (ctx.author.id,)))["n"]
        embed = discord.Embed(title=f"{ctx.author.display_name}'s trainer card", color=discord.Color.gold())
        embed.add_field(name="Coins", value=f"{player['coins']:,} 🪙")
        embed.add_field(name="Pokémon owned", value=str(owned))
        embed.add_field(name="Total caught", value=str(player["total_caught"]))
        embed.add_field(name="Shinies caught", value=f"{player['shiny_caught']} ✨")
        embed.add_field(name="Pokédex", value=f"{dex}/{max(self.names) if self.names else MAX_SPECIES}")
        embed.add_field(name="Battles", value=f"{player['battles_won']}W / {player['battles_lost']}L")
        embed.add_field(name="Daily streak", value=str(player["daily_streak"]))
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="daily", help="Claim your daily coins (streaks pay more).")
    async def daily(self, ctx):
        if not await self.require_player(ctx):
            return
        uid = ctx.author.id

        def work(conn):
            player = ps.get_player(conn, uid)
            now = int(time.time())
            if now - player["daily_last"] < DAILY_COOLDOWN:
                return "wait", player["daily_last"] + DAILY_COOLDOWN
            streak = player["daily_streak"] + 1 if now - player["daily_last"] < 48 * 3600 else 1
            reward = 100 + min(streak, 10) * 20
            conn.execute(
                "UPDATE players SET coins = coins + ?, daily_last = ?, daily_streak = ? WHERE user_id = ?",
                (reward, now, streak, uid),
            )
            return "ok", reward, streak

        res = await self.bot.db.transaction(work)
        if res[0] == "wait":
            return await ctx.send(f"⏳ You already claimed today's reward. Come back <t:{res[1]}:R>.")
        await ctx.send(f"🎁 You claimed **{res[1]} 🪙**! Daily streak: **{res[2]}** (come back within 48h to keep it).")

    @commands.command(name="shop", help="See what you can buy with coins.")
    async def shop(self, ctx):
        embed = discord.Embed(title="🛒 Poké Shop", description=f"Buy with `{PREFIX}buy <item> [amount]`, use with `{PREFIX}use <item>`.", color=discord.Color.green())
        for item in SHOP.values():
            embed.add_field(name=f"{item['emoji']} {item['name']}: {item['price']} 🪙", value=item["desc"], inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="buy", usage="<item> [amount]", help="Buy an item from the shop.")
    async def buy(self, ctx, *, text: str):
        if not await self.require_player(ctx):
            return
        name, amount = split_item_amount(text)
        key = find_item(name)
        if not key:
            return await ctx.send(f"❌ I don't sell that. See `{PREFIX}shop`.")
        if not 1 <= amount <= 99:
            return await ctx.send("❌ Amount must be between 1 and 99.")
        item = SHOP[key]
        cost = item["price"] * amount
        uid = ctx.author.id

        def work(conn):
            player = ps.get_player(conn, uid)
            if player["coins"] < cost:
                return player["coins"]
            ps.add_coins(conn, uid, -cost)
            ps.add_item(conn, uid, key, amount)
            return None

        short = await self.bot.db.transaction(work)
        if short is not None:
            return await ctx.send(f"❌ You need **{cost:,} 🪙** but only have **{short:,} 🪙**.")
        await ctx.send(f"✅ Bought **{amount}× {item['name']}** for **{cost:,} 🪙**.")

    @commands.command(name="bag", aliases=["inventory", "inv"], help="Show your items.")
    async def bag(self, ctx):
        player = await self.require_player(ctx)
        if not player:
            return
        rows = await self.bot.db.fetchall("SELECT item, qty FROM items WHERE user_id = ? AND qty > 0", (ctx.author.id,))
        lines = [f"{SHOP[r['item']]['emoji']} **{SHOP[r['item']]['name']}** ×{r['qty']}" for r in rows if r["item"] in SHOP]
        embed = discord.Embed(title=f"{ctx.author.display_name}'s bag", description="\n".join(lines) or "Empty. Visit the `!shop`!", color=discord.Color.green())
        embed.set_footer(text=f"{player['coins']:,} coins")
        await ctx.send(embed=embed)

    @commands.command(name="use", usage="<item> [amount]", help="Use an item (rare candy, incense).")
    @commands.guild_only()
    async def use(self, ctx, *, text: str):
        if not await self.require_player(ctx):
            return
        name, amount = split_item_amount(text)
        key = find_item(name)
        if not key:
            return await ctx.send(f"❌ Unknown item. See `{PREFIX}bag`.")
        uid = ctx.author.id

        if key == "rarecandy":
            def work(conn):
                player = ps.get_player(conn, uid)
                row = ps.get_pokemon(conn, player["selected"]) if player["selected"] else None
                if not row:
                    return ("nosel",)
                if row["level"] >= MAX_LEVEL:
                    return ("max",)
                have = ps.item_qty(conn, uid, key)
                if have <= 0:
                    return ("none",)
                n = max(1, min(amount, have, MAX_LEVEL - row["level"]))
                ps.add_item(conn, uid, key, -n)
                conn.execute("UPDATE pokemon SET level = level + ?, xp = 0 WHERE id = ?", (n, row["id"]))
                return "ok", n, dict(ps.get_pokemon(conn, row["id"]))

            res = await self.bot.db.transaction(work)
            if res[0] == "nosel":
                return await ctx.send(f"❌ Select a pokémon first with `{PREFIX}select <number>`.")
            if res[0] == "max":
                return await ctx.send("❌ Your selected pokémon is already max level.")
            if res[0] == "none":
                return await ctx.send(f"❌ You don't have any Rare Candy. Buy some with `{PREFIX}buy rarecandy`.")
            _, n, row = res
            await ctx.send(f"🍬 Used **{n}** Rare Candy! Your **{self.display_name(row)}** is now level **{row['level']}**.")
            new_species = await self.try_evolve(row, row["level"])
            if new_species:
                await ctx.send(f"🌟 Wow! It evolved into **{self.label(new_species)}**!")
            return

        if SHOP[key].get("evo_item"):
            return await self._use_stone(ctx, key)

        # incense
        now = int(time.time())
        active = await self.bot.db.fetchone("SELECT expires_at FROM incense WHERE channel_id = ? AND expires_at > ?", (ctx.channel.id, now))
        if active:
            return await ctx.send(f"🕯️ Incense is already burning here (ends <t:{active['expires_at']}:R>).")

        def burn(conn):
            if ps.item_qty(conn, uid, key) <= 0:
                return False
            ps.add_item(conn, uid, key, -1)
            conn.execute(
                "INSERT OR REPLACE INTO incense (channel_id, guild_id, owner_id, expires_at) VALUES (?, ?, ?, ?)",
                (ctx.channel.id, ctx.guild.id, uid, now + INCENSE_SECONDS),
            )
            return True

        if not await self.bot.db.transaction(burn):
            return await ctx.send(f"❌ You don't have any incense. Buy one with `{PREFIX}buy incense`.")
        self.incense_next[ctx.channel.id] = time.time() + 5
        await ctx.send(f"🕯️ Incense lit! Pokémon will appear here often until <t:{now + INCENSE_SECONDS}:t>.")

    async def _use_stone(self, ctx, key):
        uid = ctx.author.id
        row = await self.bot.db.run(lambda conn: ps.selected_pokemon(conn, uid))
        if not row:
            return await ctx.send(f"❌ Select a pokémon first with `{PREFIX}select <number>`.")
        have = await self.bot.db.run(lambda conn: ps.item_qty(conn, uid, key))
        if have <= 0:
            return await ctx.send(f"❌ You don't have a {SHOP[key]['name']}. Buy one with `{PREFIX}buy {key.replace('-', '')}`.")
        species = await self.get_species(row["species_id"])
        if not species:
            return await ctx.send("⏳ I can't reach the pokédex data right now. Try again in a moment.")
        evo = item_evolution(species["evolutions"], SHOP[key]["evo_item"])
        name = self.display_name(row)
        if not evo:
            return await ctx.send(f"🤷 It won't have any effect on **{name}**. (Nothing was used up.)")

        def work(conn):
            current = ps.selected_pokemon(conn, uid)
            if not current or current["id"] != row["id"] or ps.item_qty(conn, uid, key) <= 0:
                return False
            ps.add_item(conn, uid, key, -1)
            ps.evolve(conn, row["id"], uid, evo["to"])
            return True

        if not await self.bot.db.transaction(work):
            return await ctx.send("❌ Something changed. Try again.")
        embed = discord.Embed(
            title="🌟 Your pokémon is evolving!",
            description=f"Your **{name}** evolved into **{self.label(evo['to'])}** using a {SHOP[key]['name']}!",
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=artwork_url(evo["to"], bool(row["shiny"])))
        await ctx.send(embed=embed)

    async def trade_evolve(self, pokemon_id, owner_id):
        """Some pokémon (Kadabra, Machoke...) evolve when traded. Returns (old, new) names or None."""
        row = await self.bot.db.run(lambda conn: ps.get_pokemon(conn, pokemon_id))
        if not row or row["owner_id"] != owner_id:
            return None
        species = await self.get_species(row["species_id"])
        evo = trade_evolution(species["evolutions"]) if species else None
        if not evo:
            return None
        await self.bot.db.transaction(lambda conn: ps.evolve(conn, pokemon_id, owner_id, evo["to"]))
        return self.display_name(row), self.label(evo["to"])

    @commands.command(name="pay", usage="@user <amount>", help="Give coins to another trainer.")
    @commands.guild_only()
    async def pay(self, ctx, user: discord.Member, amount: int):
        if not await self.require_player(ctx):
            return
        if user.bot or user.id == ctx.author.id:
            return await ctx.send("❌ You can't pay that user.")
        if not 1 <= amount <= 1_000_000:
            return await ctx.send("❌ Amount must be between 1 and 1,000,000.")

        def work(conn):
            if not ps.get_player(conn, user.id):
                return "noplayer"
            if ps.get_player(conn, ctx.author.id)["coins"] < amount:
                return "poor"
            ps.add_coins(conn, ctx.author.id, -amount)
            ps.add_coins(conn, user.id, amount)
            return "ok"

        res = await self.bot.db.transaction(work)
        if res == "noplayer":
            return await ctx.send(f"❌ {user.display_name} hasn't started the game yet.")
        if res == "poor":
            return await ctx.send("❌ You don't have that many coins.")
        await ctx.send(f"💸 {ctx.author.mention} paid {user.mention} **{amount:,} 🪙**.", allowed_mentions=discord.AllowedMentions(users=[user]))

    @commands.command(name="leaderboard", aliases=["lb", "top"], usage="[catches|shinies|coins|pokedex]", help="Top trainers.")
    async def leaderboard(self, ctx, category: str = "catches"):
        category = category.lower()
        if category not in LEADERBOARDS:
            options = ", ".join("`" + c + "`" for c in LEADERBOARDS)
            return await ctx.send(f"❌ Pick one of: {options}.")
        column, title = LEADERBOARDS[category]
        if column is None:
            rows = await self.bot.db.fetchall(
                "SELECT user_id, COUNT(*) AS score FROM pokedex GROUP BY user_id ORDER BY score DESC LIMIT 10"
            )
        else:
            rows = await self.bot.db.fetchall(
                f"SELECT user_id, {column} AS score FROM players WHERE {column} > 0 ORDER BY {column} DESC LIMIT 10"
            )
        if not rows:
            return await ctx.send("Nobody is on this leaderboard yet.")
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows):
            rank = medals[i] if i < 3 else "`" + str(i + 1) + ".`"
            lines.append(f"{rank} <@{r['user_id']}> — **{r['score']:,}**")
        await ctx.send(embed=discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold()))

    # ================================================================ commands: trade
    async def _do_trade(self, ctx, user, my_num, their_num):
        if not await self.require_player(ctx):
            return
        if user.bot or user.id == ctx.author.id:
            return await ctx.send("❌ You can't trade with that user.")

        def look(conn):
            return (
                ps.get_player(conn, user.id),
                ps.get_pokemon_by_num(conn, ctx.author.id, my_num),
                ps.get_pokemon_by_num(conn, user.id, their_num) if their_num else None,
            )

        other, mine, theirs = await self.bot.db.run(look)
        if not other:
            return await ctx.send(f"❌ {user.display_name} hasn't started the game yet.")
        if not mine:
            return await ctx.send("❌ You don't own a pokémon with that number.")
        if mine["favorite"]:
            return await ctx.send(f"❌ #{mine['num']} is a favorite. Unfavorite it first.")
        if their_num and not theirs:
            return await ctx.send(f"❌ {user.display_name} doesn't own a pokémon with that number.")
        if theirs and theirs["favorite"]:
            return await ctx.send(f"❌ #{theirs['num']} is one of {user.display_name}'s favorites.")

        def describe(row):
            return f"**{self.label(row['species_id'])}** (Lvl {row['level']}, {iv_percent(ps.ivs_of(row))}%)"

        offer = f"{ctx.author.mention} offers {describe(mine)}"
        offer += f" in exchange for {user.mention}'s {describe(theirs)}." if theirs else f" to {user.mention} as a gift."
        embed = discord.Embed(title="🔄 Trade offer", description=offer, color=discord.Color.orange())
        view = ConfirmView({user.id}, "Accept", "Decline", timeout=60)
        msg = await ctx.send(content=user.mention, embed=embed, view=view, allowed_mentions=discord.AllowedMentions(users=[user, ctx.author]))
        await view.wait()

        if not view.value:
            embed.title = "❌ Trade declined" if view.value is False else "⌛ Trade expired"
            return await msg.edit(content=None, embed=embed, view=None)

        a_id, b_id = mine["id"], theirs["id"] if theirs else None

        def swap(conn):
            a, b = ps.get_pokemon(conn, a_id), ps.get_pokemon(conn, b_id) if b_id else None
            if not a or a["owner_id"] != ctx.author.id or a["favorite"]:
                return False
            if b_id and (not b or b["owner_id"] != user.id or b["favorite"]):
                return False
            ps.transfer(conn, a_id, user.id)
            if b_id:
                ps.transfer(conn, b_id, ctx.author.id)
            return True

        ok = await self.bot.db.transaction(swap)
        embed.title = "✅ Trade complete!" if ok else "❌ Trade failed (a pokémon changed owner)"
        embed.color = discord.Color.green() if ok else discord.Color.red()
        if ok:
            evolved = []
            for pid, new_owner in ((a_id, user), (b_id, ctx.author)):
                if pid:
                    result = await self.trade_evolve(pid, new_owner.id)
                    if result:
                        evolved.append(f"✨ {new_owner.mention}'s **{result[0]}** evolved into **{result[1]}**!")
            if evolved:
                embed.description += "\n\n" + "\n".join(evolved)
        await msg.edit(content=None, embed=embed, view=None)
        if ok:
            self.bot.dispatch("scade_data_changed")

    @commands.command(name="trade", usage="@user <your number> [their number]", help="Offer a swap (or a gift) to another trainer.")
    @commands.guild_only()
    async def trade(self, ctx, user: discord.Member, my_num: int, their_num: int = None):
        await self._do_trade(ctx, user, my_num, their_num)

    @commands.command(name="give", usage="@user <number>", help="Gift one of your pokémon.")
    @commands.guild_only()
    async def give(self, ctx, user: discord.Member, my_num: int):
        await self._do_trade(ctx, user, my_num, None)

    # ================================================================ commands: admin
    @commands.command(name="redirect", aliases=["spawnchannel"], usage="[#channel ... | clear]", help="Choose where wild pokémon spawn. (Manage Server)")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def redirect(self, ctx, *, arg: str = None):
        gid = ctx.guild.id
        channels = ctx.message.channel_mentions
        if arg and arg.strip().lower() == "clear":
            ids = []
        elif channels:
            ids = [c.id for c in channels][:10]
        else:
            current = await self.spawn_channels(gid)
            where = ", ".join(f"<#{c}>" for c in current) if current else "the channel where people are chatting"
            return await ctx.send(f"Wild pokémon currently spawn in: {where}\nChange it with `{PREFIX}redirect #channel #channel2`, or `{PREFIX}redirect clear`.")
        await self.bot.db.execute(
            "INSERT INTO guild_settings (guild_id, spawn_channels) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET spawn_channels = excluded.spawn_channels",
            (gid, json.dumps(ids)),
        )
        self.spawn_cfg[gid] = ids
        self.bot.dispatch("scade_data_changed")
        await ctx.send("✅ Spawns will appear in " + (", ".join(f"<#{c}>" for c in ids) if ids else "whichever channel is active") + ".")

    @commands.command(name="forcespawn", usage="[pokémon]", help="Spawn a wild pokémon right now. (Manage Server)")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def forcespawn(self, ctx, *, name: str = None):
        sid = None
        if name:
            sid = self.lookup_species(name)
            if not sid:
                return await ctx.send("❌ I don't know that pokémon.")
        if not await self.spawn(ctx.channel, sid):
            await ctx.send("⏳ I'm still loading the pokémon list. Try again in a minute.")


async def setup(bot):
    await bot.add_cog(Pokemon(bot))
