import discord
from discord.ext import commands
import random
import aiohttp
import asyncio
import re
from ..db import db  # Import your shared Database instance

class GuessPokemon(commands.Cog):
    def __init__(self, bot, pokemon_list):
        self.bot = bot
        self.pokemon_list = pokemon_list
        self.message_counts = {}  # {guild_id: count}
        self.active_games = {}    # {channel_id: pokemon_name}

    def is_guess_valid(self, message):
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
                    # Fetch base experience from PokeAPI
                    async with aiohttp.ClientSession() as session:
                        async with session.get(f"https://pokeapi.co/api/v2/pokemon/{name.lower()}") as resp:
                            data = await resp.json()
                            base_exp = data.get("base_experience", 50)  # fallback if not present

                    # Award EXP as points
                    await db.add_points(guess.author.id, base_exp)
                    await channel.send(f"✅ {guess.author.mention} got it! It was **{name.title()}**!")
                    await channel.send(f"💰 You earned **{base_exp} EXP** for guessing {name.title()}!")
                    break
                else:
                    await channel.send("❌ Nope, try again!")
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

        if self.message_counts[gid] >= 100 and message.channel.id not in self.active_games:
            self.message_counts[gid] = 0
            await self.spawn_pokemon_game(message.channel)

    @commands.command(name="guesspoke")
    async def guess_pokemon_command(self, ctx):
        if ctx.channel.id in self.active_games:
            await ctx.send("⚠️ A Pokémon is already active here!")
            return
        await self.spawn_pokemon_game(ctx.channel)

    @commands.command(name="hint")
    async def give_hint(self, ctx):
        if ctx.channel.id not in self.active_games:
            await ctx.send("❌ No active Pokémon to guess right now!")
            return

        name = self.active_games[ctx.channel.id].lower()
        letter_indices = [i for i, c in enumerate(name) if c.isalpha()]

        revealed = set()
        if letter_indices:
            revealed.add(letter_indices[0])
            revealed.add(letter_indices[-1])
            inner = letter_indices[1:-1]
            reveal_count = min(2, len(inner))
            revealed.update(random.sample(inner, k=reveal_count))

        display = []
        for i, c in enumerate(name):
            if c.isalpha():
                display.append(c.upper() if i in revealed else "_")
            else:
                display.append(c)

        hint = "\u2009".join(display)
        await ctx.send(f"💡 Hint: `{hint}`")

    @commands.command(name="points")
    async def check_points(self, ctx):
        points = await db.get_points(ctx.author.id)
        await ctx.send(f"🏆 {ctx.author.display_name}, you have **{points}** points!")

async def setup(bot):
    await db.connect()
    url = "https://pokeapi.co/api/v2/pokemon?limit=1025"
    pokemon_list = []

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            for i, entry in enumerate(data['results'], start=1):
                name = entry['name']
                pokemon_list.append({"name": name, "id": i})

    await bot.add_cog(GuessPokemon(bot, pokemon_list))
