import discord
from discord.ext import commands
import os
import traceback
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 🔥 Required for on_member_join
intents.guilds = True
intents.reactions = True


# help_command=None because we ship our own, nicer one in commands/helpcmd.py
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Every cog the bot should load. If one fails, the rest still load.
EXTENSIONS = [
    "jokes.fun",
    "commands.helpcmd",
    "commands.locker",
    "commands.welcomer",
    "commands.purge",  # All other moderation like ban, kick, mute is here too
    "commands.recall",
    "commands.Ah",
    "commands.translator",
    "commands.av",
    "commands.emoji_manager",
    "commands.antiabuse",
    "commands.rr",
    "commands.poll",
    "commands.afk",
    "commands.showoff_sunday",
    "commands.invisible_spy",
    "games.guesspoke",
]


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name="with the world Sir Shiny created!"))

    # Load reaction roles data manually
    rr_cog = bot.get_cog("ReactionRoles")
    if rr_cog:
        await rr_cog.load_reaction_roles()
    else:
        print("⚠️ ReactionRoles cog not found. Skipping reaction role loading.")


@bot.event
async def setup_hook():
    for ext in EXTENSIONS:
        try:
            await bot.load_extension(ext)
            print(f"✅ Loaded {ext}")
        except Exception as e:
            # One broken cog must not stop the others from loading
            print(f"❌ Failed to load {ext}: {type(e).__name__}: {e}")
            traceback.print_exc()


def usage_of(ctx) -> str:
    cmd = ctx.command
    sig = cmd.usage if cmd.usage is not None else cmd.signature
    return f"{ctx.clean_prefix}{cmd.qualified_name} {sig}".strip()


@bot.event
async def on_command_error(ctx, error):
    """Tell people what went wrong instead of failing silently."""
    if isinstance(error, commands.CommandNotFound):
        return
    # Commands/cogs that define their own error handler (e.g. !purge) keep control
    if ctx.command and ctx.command.has_error_handler():
        return
    if ctx.cog and ctx.cog.has_error_handler():
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"❗ You're missing `{error.param.name}`.\n"
            f"**Usage:** `{usage_of(ctx)}`\n"
            f"Need examples? Try `{ctx.clean_prefix}help {ctx.command.qualified_name}`"
        )
    elif isinstance(error, (commands.BadArgument, commands.BadUnionArgument, commands.ArgumentParsingError)):
        await ctx.send(
            f"❗ I couldn't understand that input.\n"
            f"**Usage:** `{usage_of(ctx)}`\n"
            f"Try `{ctx.clean_prefix}help {ctx.command.qualified_name}` for examples."
        )
    elif isinstance(error, commands.MissingPermissions):
        perms = ", ".join(p.replace("_", " ").title() for p in error.missing_permissions)
        await ctx.send(f"❌ You need the **{perms}** permission to use that.")
    elif isinstance(error, commands.BotMissingPermissions):
        perms = ", ".join(p.replace("_", " ").title() for p in error.missing_permissions)
        await ctx.send(f"❌ I'm missing the **{perms}** permission to do that.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Easy there! Try again in **{error.retry_after:.1f}s**.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ That command only works inside a server.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You can't use that command.")
    else:
        original = getattr(error, "original", error)
        traceback.print_exception(type(original), original, original.__traceback__)
        await ctx.send(f"💥 Something broke inside `{ctx.clean_prefix}{ctx.command}`: `{type(original).__name__}: {str(original)[:150]}`")


keep_alive()

TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN is None:
    raise ValueError("DISCORD_TOKEN environment variable not set.")
bot.run(TOKEN)
