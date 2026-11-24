"""
Pokémon battles: !moves, !team, !battle @user

Two trainers fight with up to 3 pokémon each. Every turn both pick a move with buttons
(the choice is private), then the faster pokémon attacks first. Winner earns coins + XP.
"""

import asyncio
import time
import traceback

import discord
from discord.ext import commands

from games import pokestore as ps
from games.battle import (
    MAX_TEAM,
    TIER_LEVELS,
    TYPE_EMOJI,
    Battle,
    Side,
    build_combatant,
    hp_bar,
    moves_for,
)
from games.pokemon import ConfirmView
from games.pokedata import artwork_url, iv_percent

PREFIX = "!"
TURN_SECONDS = 90
MAX_LOG_CHARS = 1500


class ArenaView(discord.ui.View):
    """The shared buttons under the battle message."""

    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="Choose move", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def choose(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.session.open_choice(interaction)

    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def forfeit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.session.press_forfeit(interaction)


class MoveView(discord.ui.View):
    """Private (only you can see it) list of your pokémon's moves for this turn."""

    def __init__(self, session, user_id, turn, moves):
        super().__init__(timeout=TURN_SECONDS)
        for move in moves:
            button = discord.ui.Button(
                label=f"{move.name} ({move.power})", style=discord.ButtonStyle.secondary, emoji=TYPE_EMOJI.get(move.type)
            )
            button.callback = self._make_callback(session, user_id, turn, move)
            self.add_item(button)

    @staticmethod
    def _make_callback(session, user_id, turn, move):
        async def callback(interaction: discord.Interaction):
            await session.submit(interaction, user_id, turn, move)

        return callback


class BattleSession:
    def __init__(self, cog, ctx, battle: Battle, users):
        self.cog = cog
        self.ctx = ctx
        self.battle = battle
        self.users = {battle.a.user_id: users[0], battle.b.user_id: users[1]}
        self.choices = {}  # user_id -> Move
        self.event = asyncio.Event()
        self.message = None
        self.view = ArenaView(self)
        self.timed_out = False
        self.last_log = ["The battle begins!"]

    # ------------------------------------------------------------ display
    def side_of(self, user_id):
        return self.battle.a if self.battle.a.user_id == user_id else self.battle.b

    def embed(self, final=False):
        b = self.battle
        embed = discord.Embed(
            title=f"⚔️ {b.a.name}  vs  {b.b.name}",
            description="\n".join(self.last_log)[:MAX_LOG_CHARS],
            color=discord.Color.red(),
        )
        for side in (b.a, b.b):
            c = side.current
            types = " ".join(TYPE_EMOJI.get(t, "") for t in c.types)
            embed.add_field(
                name=f"{side.name}: {c.name} Lv.{c.level} {types}",
                value=f"`{hp_bar(c.hp, c.max_hp)}` {max(0, c.hp)}/{c.max_hp} HP\nPokémon left: {side.alive}/{len(side.team)}",
                inline=True,
            )
        if final:
            embed.set_footer(text="Battle finished")
        else:
            waiting = [self.users[u].display_name for u in self.users if u not in self.choices]
            embed.set_footer(text=f"Turn {b.turn} • waiting for: {', '.join(waiting)} • {TURN_SECONDS}s per turn")
        return embed

    async def refresh(self, final=False):
        try:
            await self.message.edit(embed=self.embed(final), view=None if final else self.view)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------- interactions
    async def open_choice(self, interaction):
        uid = interaction.user.id
        if uid not in self.users:
            return await interaction.response.send_message("You're not part of this battle 😉", ephemeral=True)
        if self.battle.over:
            return await interaction.response.send_message("The battle is over.", ephemeral=True)
        if uid in self.choices:
            return await interaction.response.send_message("✅ You already chose. Waiting for your opponent...", ephemeral=True)
        side = self.side_of(uid)
        view = MoveView(self, uid, self.battle.turn, side.current.moves)
        await interaction.response.send_message(
            f"Choose a move for **{side.current.name}** (power in brackets):", view=view, ephemeral=True
        )

    async def submit(self, interaction, uid, turn, move):
        if interaction.user.id != uid:
            return await interaction.response.send_message("Those buttons aren't yours.", ephemeral=True)
        if turn != self.battle.turn or self.battle.over:
            return await interaction.response.edit_message(content="⌛ That turn is already over.", view=None)
        if uid in self.choices:
            return await interaction.response.edit_message(content="✅ You already chose this turn.", view=None)
        self.choices[uid] = move
        await interaction.response.edit_message(content=f"✅ You chose **{move.name}**. Waiting for your opponent...", view=None)
        if len(self.choices) == 2:
            self.event.set()

    async def press_forfeit(self, interaction):
        uid = interaction.user.id
        if uid not in self.users:
            return await interaction.response.send_message("You're not part of this battle 😉", ephemeral=True)
        if not self.battle.over:
            self.last_log = self.battle.forfeit(uid)
            self.event.set()
        await interaction.response.defer()

    # -------------------------------------------------------------- loop
    async def run(self):
        b = self.battle
        self.message = await self.ctx.send(embed=self.embed(), view=self.view)
        while not b.over:
            self.event.clear()
            try:
                await asyncio.wait_for(self.event.wait(), timeout=TURN_SECONDS)
            except asyncio.TimeoutError:
                idle = [u for u in self.users if u not in self.choices]
                if len(idle) == 2:
                    self.timed_out = True  # nobody played: call it a draw
                    break
                self.last_log = b.forfeit(idle[0])
                self.last_log.append("(ran out of time)")
                break
            if b.over:
                break  # someone pressed Forfeit
            move_a, move_b = self.choices[b.a.user_id], self.choices[b.b.user_id]
            self.choices = {}
            self.last_log = b.resolve_turn(move_a, move_b)
            await self.refresh()
        await self.finish()

    async def finish(self):
        b = self.battle
        await self.refresh(final=True)
        if self.timed_out or b.winner is None:
            return await self.ctx.send("🤝 Nobody made a move: the battle ended in a draw. No rewards.")
        winner, loser = b.winner, (b.b if b.winner is b.a else b.a)
        await self.cog.reward(self.ctx, winner, loser)


# =================================================================== the cog
class PokemonBattle(commands.Cog):
    """Moves, teams and battles."""

    def __init__(self, bot):
        self.bot = bot
        self.busy = set()  # user ids currently fighting

    @property
    def core(self):
        return self.bot.get_cog("Pokemon")

    # -------------------------------------------------------------- moves
    @commands.command(name="moves", usage="[number]", help="Show the moves of a pokémon (it learns stronger ones as it levels).")
    async def moves(self, ctx, number: int = None):
        core = self.core
        if not core or not await core.require_player(ctx):
            return
        row = await self.bot.db.run(
            lambda conn: ps.get_pokemon_by_num(conn, ctx.author.id, number) if number else ps.selected_pokemon(conn, ctx.author.id)
        )
        if not row:
            return await ctx.send("❌ I couldn't find that pokémon.")
        species = await core.get_species(row["species_id"])
        if not species:
            return await ctx.send("⏳ I can't reach the pokédex data right now. Try again in a moment.")
        lines = [
            f"{m.label()} • {m.category.title()} • Power **{m.power}** • Accuracy **{m.accuracy}%**"
            for m in moves_for(species["types"], row["level"])
        ]
        nxt = next((lv for lv in TIER_LEVELS if lv > row["level"]), None)
        embed = discord.Embed(
            title=f"Level {row['level']} {core.display_name(row)}: moves",
            description="\n".join(lines),
            color=core.embed_color(species),
        )
        embed.set_footer(text=f"Stronger moves unlock at level {nxt}" if nxt else "All moves unlocked!")
        embed.set_thumbnail(url=artwork_url(row["species_id"], bool(row["shiny"])))
        await ctx.send(embed=embed)

    # --------------------------------------------------------------- team
    @commands.command(name="team", usage="[add|remove|clear] [number]", help="Set your battle team (up to 3 pokémon).")
    async def team(self, ctx, action: str = None, number: int = None):
        core = self.core
        if not core or not await core.require_player(ctx):
            return
        uid = ctx.author.id
        action = (action or "").lower()

        if action in ("add", "remove", "rm"):
            if number is None:
                return await ctx.send(f"❌ Tell me which pokémon number: `{PREFIX}team {action} 12`.")

            def work(conn):
                row = ps.get_pokemon_by_num(conn, uid, number)
                if not row:
                    return "missing", None
                if action == "add":
                    return ps.team_add(conn, uid, row["id"]), row
                return ("ok" if ps.team_remove(conn, uid, row["id"]) else "notin"), row

            status, row = await self.bot.db.transaction(work)
            messages = {
                "missing": "❌ You don't own a pokémon with that number.",
                "dup": "❌ That pokémon is already on your team.",
                "full": f"❌ Your team is full ({MAX_TEAM}). Remove someone first.",
                "notin": "❌ That pokémon isn't on your team.",
            }
            if status in messages:
                return await ctx.send(messages[status])
            verb = "added to" if action == "add" else "removed from"
            return await ctx.send(f"✅ **{core.label(row['species_id'])}** (#{number}) {verb} your team.")

        if action == "clear":
            await self.bot.db.transaction(lambda conn: ps.team_clear(conn, uid))
            return await ctx.send("✅ Team cleared. Battles will use your selected pokémon.")
        if action:
            return await ctx.send(f"❌ Use `{PREFIX}team`, `{PREFIX}team add <number>`, `{PREFIX}team remove <number>` or `{PREFIX}team clear`.")

        rows = await self.bot.db.run(lambda conn: ps.team_rows(conn, uid))
        if not rows:
            return await ctx.send(
                f"You have no saved team, so battles use your selected pokémon.\nBuild one with `{PREFIX}team add <number>` (up to {MAX_TEAM})."
            )
        lines = [
            f"**{i}.** `#{r['num']}` {'✨ ' if r['shiny'] else ''}{core.display_name(r)} • Lvl {r['level']} • IV {iv_percent(ps.ivs_of(r))}%"
            for i, r in enumerate(rows, start=1)
        ]
        await ctx.send(embed=discord.Embed(title=f"{ctx.author.display_name}'s battle team", description="\n".join(lines), color=discord.Color.red()))

    # ------------------------------------------------------------- battle
    async def _load_side(self, user):
        """Build one trainer's team. Returns (Side, None) or (None, error text)."""
        core = self.core
        rows = await self.bot.db.run(lambda conn: ps.battle_team(conn, user.id))
        if not rows:
            return None, f"{user.display_name} has no pokémon ready. Select one with `{PREFIX}select <number>` or build a `{PREFIX}team`."
        team = []
        for row in rows:
            species = await core.get_species(row["species_id"])
            if not species:
                return None, "⏳ I can't load pokémon stats right now (the pokédex service is unreachable). Try again in a moment."
            team.append(build_combatant(row, species, core.label(row["species_id"])))
        return Side(user_id=user.id, name=user.display_name, team=team), None

    @commands.command(name="battle", aliases=["duel"], usage="@user", help="Challenge another trainer to a battle.")
    @commands.guild_only()
    async def battle(self, ctx, opponent: discord.Member):
        core = self.core
        if not core or not await core.require_player(ctx):
            return
        if opponent.bot or opponent.id == ctx.author.id:
            return await ctx.send("❌ You can't battle that user.")
        if ctx.author.id in self.busy or opponent.id in self.busy:
            return await ctx.send("❌ One of you is already in a battle.")
        if not await self.bot.db.fetchone("SELECT 1 FROM players WHERE user_id = ?", (opponent.id,)):
            return await ctx.send(f"❌ {opponent.display_name} hasn't started the game yet.")

        side_a, err = await self._load_side(ctx.author)
        if err:
            return await ctx.send(err)
        side_b, err = await self._load_side(opponent)
        if err:
            return await ctx.send(err)

        embed = discord.Embed(
            title="⚔️ Battle challenge!",
            description=(
                f"{ctx.author.mention} challenges {opponent.mention}!\n"
                f"**{side_a.name}:** " + ", ".join(f"{c.name} Lv.{c.level}" for c in side_a.team) + "\n"
                f"**{side_b.name}:** " + ", ".join(f"{c.name} Lv.{c.level}" for c in side_b.team)
            ),
            color=discord.Color.red(),
        )
        view = ConfirmView({opponent.id}, "Accept", "Decline", timeout=60)
        msg = await ctx.send(content=opponent.mention, embed=embed, view=view,
                             allowed_mentions=discord.AllowedMentions(users=[opponent]))
        await view.wait()
        if not view.value:
            embed.title = "❌ Challenge declined" if view.value is False else "⌛ Challenge expired"
            return await msg.edit(content=None, embed=embed, view=None)
        await msg.edit(content=None, embed=embed, view=None)

        if ctx.author.id in self.busy or opponent.id in self.busy:
            return await ctx.send("❌ One of you started another battle in the meantime.")
        self.busy.update({ctx.author.id, opponent.id})
        try:
            session = BattleSession(self, ctx, Battle(side_a, side_b), (ctx.author, opponent))
            await session.run()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            await ctx.send("⚠️ The battle crashed. Sorry! Nobody lost anything.")
        finally:
            self.busy.difference_update({ctx.author.id, opponent.id})

    async def reward(self, ctx, winner: Side, loser: Side):
        """Record the result, pay coins and give the winner's team XP."""
        core = self.core
        today = int(time.time()) // 86400

        def work(conn):
            win_coins, rewarded = ps.record_battle(conn, winner.user_id, True, today)
            lose_coins, _ = ps.record_battle(conn, loser.user_id, False, today)
            leveled = []
            if rewarded:
                for c in winner.team:
                    row = ps.get_pokemon(conn, c.pokemon_id)
                    if row and row["owner_id"] == winner.user_id:
                        before, after, _ = ps.award_xp(conn, c.pokemon_id, ps.WIN_XP)
                        if after > before:
                            leveled.append((dict(ps.get_pokemon(conn, c.pokemon_id)), after))
            return win_coins, lose_coins, rewarded, leveled

        win_coins, lose_coins, rewarded, leveled = await self.bot.db.transaction(work)
        text = f"🏆 **{winner.name}** won the battle!"
        if rewarded:
            text += f"\n+{win_coins} 🪙 and {ps.WIN_XP} XP for each of {winner.name}'s pokémon. {loser.name} gets +{lose_coins} 🪙 for playing."
        else:
            text += f"\n(No rewards: someone reached today's limit of {ps.BATTLE_DAILY_REWARDS} rewarded battles.)"
        for row, level in leveled:
            new_species = await core.try_evolve(row, level)
            text += f"\n⬆️ {core.display_name(row)} reached level {level}"
            if new_species:
                text += f" and evolved into **{core.label(new_species)}**!"
        await ctx.send(text)
        self.bot.dispatch("scade_data_changed")


async def setup(bot):
    await bot.add_cog(PokemonBattle(bot))
