import discord
from discord.ext import commands
import random
import aiohttp
import asyncio
import re

class GuessPokemon(commands.Cog):
    def __init__(self, bot, pokemon_list):
        self.bot = bot
        self.pokemon_list = pokemon_list
        self.message_counts = {}  # {guild_id: count}
        self.active_games = {}    # {channel_id: pokemon_name}

    def is_guess_valid(self, message):
        """Check if message could be a guess (e.g., not an emoji or link)"""
        return re.match(r"^[a-zA-Z\s\-'.]+$", message.content.strip())

    async def spawn_pokemon_game(self, channel):
        pokemon = random.choice(self.pokemon_list)
        name = pokemon["name"]
        poke_id = pokemon["id"]
        image_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{poke_id}.png"

        await channel.send("🕵️ A wild Pokémon appeared! Guess its name! You have 20 seconds.")
        await channel.send(image_url)

        self.active_games[channel.id] = name

        def check(m):
            return (
                m.channel.id == channel.id
                and m.author != self.bot.user
                and self.is_guess_valid(m)
            )

        try:
            while True:
                guess = await self.bot.wait_for("message", timeout=20.0, check=check)
                if guess.content.lower().strip() == name.lower():
                    await channel.send(f"✅ {guess.author.mention} got it! It was **{name.title()}**!")
                    break
                else:
                    await channel.send(f"❌ Nope, try again!")
        except asyncio.TimeoutError:
            await channel.send(f"⏰ Time's up! The Pokémon was **{name.title()}**.")
        finally:
            self.active_games.pop(channel.id, None)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return

        gid = message.guild.id
        self.message_counts[gid] = self.message_counts.get(gid, 0) + 1

        # Don't trigger inside already-active guess channel
        if (
            self.message_counts[gid] >= 100
            and message.channel.id not in self.active_games
        ):
            self.message_counts[gid] = 0
            await self.spawn_pokemon_game(message.channel)

    @commands.command(name="guesspoke")
    async def guess_pokemon_command(self, ctx):
        """Manually start a guess-the-Pokémon game"""
        if ctx.channel.id in self.active_games:
            await ctx.send("⚠️ A Pokémon is already active here!")
            return
        await self.spawn_pokemon_game(ctx.channel)

    @commands.command(name="hint")
    async def give_hint(self, ctx):
        """Gives a smart hint for the current Pokémon"""
        if ctx.channel.id not in self.active_games:
            await ctx.send("❌ No active Pokémon to guess right now!")
            return

        name = self.active_games[ctx.channel.id]
        name = name.lower()

        # Choose 1–2 random inner letters to reveal (not first or last)
        if len(name) > 3:
            indices = list(range(1, len(name) - 1))
            reveal_count = min(2, len(indices))
            revealed_indices = random.sample(indices, k=reveal_count)
        else:
            revealed_indices = []

        # Always reveal first and last letter
        revealed = [
            c.upper() if i == 0 or i == len(name) - 1 or i in revealed_indices else "_"
            for i, c in enumerate(name)
        ]
        hint = " ".join(revealed)
        await ctx.send(f"💡 Hint: The name is **{hint}**")


async def setup(bot):
    # Load Pokémon names and IDs at load time (not in on_ready)
    url = "https://pokeapi.co/api/v2/pokemon?limit=1025"
    pokemon_list = []

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            for i, entry in enumerate(data['results'], start=1):
                name = entry['name']
                pokemon_list.append({"name": name, "id": i})

    await bot.add_cog(GuessPokemon(bot, pokemon_list))
