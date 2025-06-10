import discord
from discord.ext import commands
import random
import aiohttp
import asyncio

class GuessPokemon(commands.Cog):
    def __init__(self, bot, pokemon_list):
        self.bot = bot
        self.pokemon_list = pokemon_list

    @commands.command(name="guesspoke")
    async def guess_pokemon(self, ctx):
        """Start a guess-the-Pokémon game"""
        pokemon = random.choice(self.pokemon_list)
        name = pokemon["name"]
        poke_id = pokemon["id"]
        image_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{poke_id}.png"

        await ctx.send("🕵️ A wild Pokémon appeared! Guess its name! You have 15 seconds.")
        await ctx.send(image_url)

        def check(m):
            return m.channel == ctx.channel and m.author != self.bot.user

        try:
            guess = await self.bot.wait_for("message", timeout=15.0, check=check)
            if guess.content.lower().strip() == name.lower():
                await ctx.send(f"✅ Correct! It's **{name.title()}**!")
            else:
                await ctx.send(f"❌ Nope! It was **{name.title()}**.")
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time's up! The Pokémon was **{name.title()}**.")

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
