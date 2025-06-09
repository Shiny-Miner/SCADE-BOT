import discord
from discord.ext import commands
import os
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 🔥 Required for on_member_join
intents.guilds = True
intents.reactions = True


bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.playing, 
        name="with the world Sir Shiny created!"
    ))

    rr_cog = bot.get_cog("ReactionRoles")
    if rr_cog:
        rr_cog.load_roles_from_json()
    else:
        print("⚠️ ReactionRoles cog not loaded yet.")

# Load all jokes from the "jokes" folder
@bot.event
async def setup_hook():
    await bot.load_extension("jokes.fun")
    await bot.load_extension("commands.locker")  # You can add more like cogs.admin, cogs.games etc.
    await bot.load_extension("commands.welcomer")
    await bot.load_extension("commands.purge") # All other moderation like ban, kick, mute is here too
    await bot.load_extension("commands.recall")
    await bot.load_extension("commands.Ah")
    await bot.load_extension("commands.translator")
    await bot.load_extension("commands.av")
    await bot.load_extension("commands.emoji_manager")
    await bot.load_extension("commands.antiabuse")
    await bot.load_extension("commands.rr")
    await bot.load_extension("commands.poll")
    await bot.load_extension("commands.afk")
    await bot.load_extension("commands.showoff_sunday")
    await bot.load_extension("commands.invisible_spy")


keep_alive()

TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_TOKEN environment variable not set.")
bot.run(TOKEN)
