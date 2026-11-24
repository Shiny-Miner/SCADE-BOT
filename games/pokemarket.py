"""
Pokémon market: sell your pokémon to anyone for coins.

!market list <number> <price> | search [options] | buy <id> | remove <id> | mine | info <id>
"""

import math

import discord
from discord.ext import commands

from games import pokestore as ps
from games.pokedata import LEGENDARY, MYTHICAL, ULTRA_BEASTS, iv_percent, norm, pretty_name
from games.pokemon import ConfirmView, Paginator

PREFIX = "!"
PER_PAGE = 10

SORTS = {
    "new": "m.id DESC",
    "price": "m.price ASC, m.id ASC",
    "level": "p.level DESC, m.id ASC",
    "iv": "(p.iv_hp + p.iv_atk + p.iv_def + p.iv_spa + p.iv_spd + p.iv_spe) DESC, m.id ASC",
}

USAGE = (
    f"`{PREFIX}market search [page] [shiny] [legendary|mythical|ub] [sort:price|level|iv|new] [name:pika]`\n"
    f"`{PREFIX}market list <your pokémon number> <price>`\n"
    f"`{PREFIX}market buy <listing id>`\n"
    f"`{PREFIX}market info <listing id>`\n"
    f"`{PREFIX}market mine`  •  `{PREFIX}market remove <listing id>`"
)


class PokemonMarket(commands.Cog):
    """Buy and sell pokémon for coins."""

    def __init__(self, bot):
        self.bot = bot

    @property
    def core(self):
        return self.bot.get_cog("Pokemon")

    # ------------------------------------------------------------ helpers
    def _line(self, row):
        core = self.core
        name = core.label(row["species_id"])
        if row["nickname"]:
            name = f"{row['nickname']} ({name})"
        marks = "✨ " if row["shiny"] else ""
        return (
            f"`{row['listing_id']:>4}`  {marks}**{name}** • Lvl. {row['level']} • IV: {iv_percent(ps.ivs_of(row))}% • "
            f"**{row['price']:,} 🪙**"
        )

    def _parse(self, text):
        flags = {"page": 1, "shiny": False, "rarity": None, "sort": "new", "name": None}
        for token in (text or "").split():
            low = token.lower()
            if low.isdigit():
                flags["page"] = max(1, int(low))
            elif low == "shiny":
                flags["shiny"] = True
            elif low in ("legendary", "mythical", "ub"):
                flags["rarity"] = low
            elif low.startswith("sort:") and low[5:] in SORTS:
                flags["sort"] = low[5:]
            elif low.startswith("name:") and len(low) > 5:
                flags["name"] = token[5:]
            else:
                return None
        return flags

    def _where(self, flags, seller_id=None):
        where, params = ["1 = 1"], []
        if seller_id:
            where.append("m.seller_id = ?")
            params.append(seller_id)
        if flags["shiny"]:
            where.append("p.shiny = 1")
        if flags["rarity"]:
            group = {"legendary": LEGENDARY, "mythical": MYTHICAL, "ub": ULTRA_BEASTS}[flags["rarity"]]
            where.append("p.species_id IN (" + ",".join(str(int(i)) for i in sorted(group)) + ")")
        if flags["name"]:
            q = norm(flags["name"])
            ids = [sid for sid, slug in self.core.names.items() if q in norm(slug) or q in norm(pretty_name(slug))][:300]
            like = "%" + flags["name"].lower().replace("%", "") + "%"
            if ids:
                where.append(f"(p.species_id IN ({','.join('?' * len(ids))}) OR LOWER(COALESCE(p.nickname, '')) LIKE ?)")
                params += ids + [like]
            else:
                where.append("LOWER(COALESCE(p.nickname, '')) LIKE ?")
                params.append(like)
        return " AND ".join(where), params

    async def _show_list(self, ctx, flags, title, seller_id=None):
        where, params = self._where(flags, seller_id)
        base = "FROM market m JOIN pokemon p ON p.id = m.pokemon_id WHERE " + where
        total = (await self.bot.db.fetchone(f"SELECT COUNT(*) AS n {base}", params))["n"]
        if total == 0:
            return await ctx.send("Nothing found on the market with those filters.")
        pages = math.ceil(total / PER_PAGE)
        order = SORTS[flags["sort"]]

        async def fetch(index):
            rows = await self.bot.db.fetchall(
                f"SELECT m.id AS listing_id, m.price, m.seller_id, p.* {base} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [PER_PAGE, index * PER_PAGE],
            )
            embed = discord.Embed(title=title, description="\n".join(self._line(r) for r in rows), color=discord.Color.green())
            embed.set_footer(text=f"Page {index + 1}/{pages} • {total} listing(s) • {PREFIX}market buy <id>")
            return embed

        page = min(flags["page"], pages) - 1
        embed = await fetch(page)
        if pages == 1:
            return await ctx.send(embed=embed)
        view = Paginator(ctx.author.id, pages, fetch, page)
        view.message = await ctx.send(embed=embed, view=view)

    # ------------------------------------------------------------ command
    @commands.command(name="market", aliases=["mk"], usage="list|search|buy|remove|mine|info ...", help="Buy and sell pokémon for coins.")
    @commands.guild_only()
    async def market(self, ctx, action: str = None, *, rest: str = ""):
        core = self.core
        if not core:
            return
        action = (action or "search").lower()
        if action.isdigit():  # "!market 2" -> page 2 of the search
            rest, action = f"{action} {rest}", "search"

        if action in ("search", "s", "browse"):
            flags = self._parse(rest)
            if flags is None:
                return await ctx.send("❌ I didn't understand that filter.\n" + USAGE)
            return await self._show_list(ctx, flags, "🛒 Pokémon market")

        if not await core.require_player(ctx):
            return
        uid = ctx.author.id

        if action == "mine":
            return await self._show_list(ctx, self._parse(""), f"{ctx.author.display_name}'s listings", seller_id=uid)

        if action == "list":
            parts = rest.replace(",", "").split()
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                return await ctx.send(f"❌ Usage: `{PREFIX}market list <your pokémon number> <price>`")
            number, price = int(parts[0]), int(parts[1])
            if not 1 <= price <= ps.MAX_PRICE:
                return await ctx.send(f"❌ Price must be between 1 and {ps.MAX_PRICE:,} 🪙.")

            def work(conn):
                row = ps.get_pokemon_by_num(conn, uid, number)
                if not row:
                    return ("missing",)
                if row["favorite"]:
                    return ("fav", row)
                player = ps.get_player(conn, uid)
                if player["selected"] == row["id"]:
                    return ("selected", row)
                count = conn.execute("SELECT COUNT(*) AS n FROM market WHERE seller_id = ?", (uid,)).fetchone()["n"]
                if count >= ps.MAX_LISTINGS:
                    return ("limit",)
                return "ok", row, ps.list_on_market(conn, uid, row["id"], price)

            res = await self.bot.db.transaction(work)
            if res[0] == "missing":
                return await ctx.send("❌ You don't own a pokémon with that number.")
            if res[0] == "fav":
                return await ctx.send("❌ That pokémon is a favorite. Unfavorite it first.")
            if res[0] == "selected":
                return await ctx.send("❌ That's your selected pokémon. Select another one first.")
            if res[0] == "limit":
                return await ctx.send(f"❌ You can have at most {ps.MAX_LISTINGS} listings.")
            _, row, listing_id = res
            self.bot.dispatch("scade_data_changed")
            fee = ps.MARKET_FEE_PERCENT
            return await ctx.send(
                f"✅ Listed your level {row['level']} **{core.label(row['species_id'])}** for **{price:,} 🪙** "
                f"(listing `{listing_id}`). You get the price minus a {fee}% fee when it sells. "
                f"Take it back any time with `{PREFIX}market remove {listing_id}`."
            )

        if action in ("remove", "cancel", "unlist"):
            if not rest.strip().isdigit():
                return await ctx.send(f"❌ Usage: `{PREFIX}market remove <listing id>`")
            num = await self.bot.db.transaction(lambda conn: ps.cancel_listing(conn, uid, int(rest.strip())))
            if num is None:
                return await ctx.send("❌ You don't have a listing with that id.")
            self.bot.dispatch("scade_data_changed")
            return await ctx.send(f"✅ Listing removed. The pokémon is back in your collection as **#{num}**.")

        if action in ("info", "buy"):
            if not rest.strip().isdigit():
                return await ctx.send(f"❌ Usage: `{PREFIX}market {action} <listing id>`")
            listing_id = int(rest.strip())
            row = await self.bot.db.fetchone(
                "SELECT m.id AS listing_id, m.price, m.seller_id, p.* FROM market m JOIN pokemon p ON p.id = m.pokemon_id WHERE m.id = ?",
                (listing_id,),
            )
            if not row:
                return await ctx.send("❌ That listing doesn't exist (maybe it just sold).")
            embed = await core.pokemon_embed(dict(row))
            embed.title = f"Listing {listing_id}: {embed.title}"
            embed.add_field(name="Price", value=f"**{row['price']:,} 🪙**\nSeller: <@{row['seller_id']}>", inline=False)

            if action == "info":
                return await ctx.send(embed=embed)

            view = ConfirmView({uid}, "Buy", "Cancel", timeout=45)
            msg = await ctx.send(content=f"Buy this pokémon for **{row['price']:,} 🪙**?", embed=embed, view=view)
            await view.wait()
            if not view.value:
                return await msg.edit(content="Purchase cancelled.", view=None)
            res = await self.bot.db.transaction(lambda conn: ps.buy_listing(conn, uid, listing_id))
            if res[0] == "gone":
                return await msg.edit(content="❌ Too slow: someone else bought it or the seller removed it.", embed=None, view=None)
            if res[0] == "own":
                return await msg.edit(content="❌ That's your own listing. Use `!market remove` to take it back.", embed=None, view=None)
            if res[0] == "poor":
                return await msg.edit(content=f"❌ You need **{res[1]:,} 🪙** but only have **{res[2]:,} 🪙**.", embed=None, view=None)
            _, price, seller_id, bought = res
            self.bot.dispatch("scade_data_changed")
            await msg.edit(
                content=f"✅ {ctx.author.display_name} bought **{core.label(bought['species_id'])}** (level {bought['level']}) for **{price:,} 🪙**!",
                embed=None, view=None,
            )
            await ctx.send(f"💰 <@{seller_id}>, your pokémon sold for **{price:,} 🪙** (minus the {ps.MARKET_FEE_PERCENT}% fee)!",
                           allowed_mentions=discord.AllowedMentions(users=True))
            return

        await ctx.send("❌ I don't know that market action.\n" + USAGE)


async def setup(bot):
    await bot.add_cog(PokemonMarket(bot))
