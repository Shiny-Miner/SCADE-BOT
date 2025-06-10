import discord
from discord.ext import commands
import random
import asyncio

class GuessPokemon(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pokemon_list = [
            {"name": "bulbasaur", "id": 1},
            {"name": "charmander", "id": 4},
            {"name": "squirtle", "id": 7},
            {"name": "pikachu", "id": 25},
            {"name": "eevee", "id": 133},
            {"name": "snorlax", "id": 143},
            {"name": "mew", "id": 151},
            {"name": "lucario", "id": 448},
            {"name": "garchomp", "id": 445},
            {"name": "greninja", "id": 658}
        ]

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
            if guess.content.lower().strip() == name:
                await ctx.send(f"✅ Correct! It's **{name.title()}**!")
            else:
                await ctx.send(f"❌ Nope! It was **{name.title()}**.")
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Time's up! The Pokémon was **{name.title()}**.")

async def setup(bot):
    await bot.add_cog(GuessPokemon(bot))
