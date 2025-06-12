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
        """Gives a hint that displays all underscores even for hidden adjacent letters."""
        if ctx.channel.id not in self.active_games:
            await ctx.send("❌ No active Pokémon to guess right now!")
            return

        name = self.active_games[ctx.channel.id].lower()
        letter_indices = [i for i, c in enumerate(name) if c.isalpha()]

        # Reveal logic
        revealed = set()
        if letter_indices:
            revealed.add(letter_indices[0])  # First letter
            revealed.add(letter_indices[-1])  # Last letter

            inner = letter_indices[1:-1]
            reveal_count = min(2, len(inner))
            revealed.update(random.sample(inner, k=reveal_count))

        # Build the display
        display = []
        for i, c in enumerate(name):
            if c.isalpha():
                display.append(c.upper() if i in revealed else "_")
            else:
                display.append(c)  # Preserve hyphen, apostrophe, etc.

        # Use THIN SPACE (U+2009) to avoid Discord collapsing characters visually
        hint = "\u2009".join(display)

        await ctx.send(f"💡 Hint: `{hint}`")  # Backticks force Discord to preserve spacing



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
