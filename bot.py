import asyncio
import os
import signal
import traceback

import discord
from discord.ext import commands

try:  # optional: read settings from a .env file next to bot.py
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from database import DEFAULT_DB_PATH, create_database, restore_from_discord
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # 🔥 Required for on_member_join
intents.guilds = True
intents.reactions = True



class ScadeBot(commands.Bot):
    """Bot with a shared SQLite database (self.db) that survives restarts."""

    db = None
    backup_blocked = None  # set to a reason string when automatic backups must pause

    async def setup_hook(self):
        await self.init_database()
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                print(f"✅ Loaded {ext}")
            except Exception as e:
                # One broken cog must not stop the others from loading
                print(f"❌ Failed to load {ext}: {type(e).__name__}: {e}")
                traceback.print_exc()

        # Hosts stop the bot with SIGTERM when redeploying: save a last backup first
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, lambda: setattr(self, "_stop_task", asyncio.create_task(self.close())))
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # Windows / unusual hosts

    async def init_database(self):
        using_postgres = bool(os.environ.get("DATABASE_URL", "").strip())
        path = os.environ.get("DB_PATH") or DEFAULT_DB_PATH
        backup_channel = os.environ.get("BACKUP_CHANNEL_ID", "").strip()

        # SQLite only: if the file vanished (host wiped the disk), try the Discord backup channel
        if not using_postgres and not os.path.exists(path) and backup_channel.isdigit():
            print("[DB] No database file found: looking for a backup in the Discord backup channel...")
            status = await restore_from_discord(self, path, int(backup_channel))
            if status == "failed":
                self.backup_blocked = "restoring from the backup channel failed at startup"
                print("[DB] ⛔ Automatic backups are paused so an empty database can't overwrite your real backups.")
            elif status == "no_backup":
                print("[DB] No backup found yet (first run?). Starting with a fresh database.")

        self.db = create_database(DEFAULT_DB_PATH)
        try:
            await self.db.connect()
        except Exception as e:
            # Don't silently fall back to another database: that would split your data in two
            raise RuntimeError(
                f"Could not connect to the database ({self.db.kind}: {self.db.path}): {type(e).__name__}: {e}\n"
                "Check DATABASE_URL (copy it again from your database provider, keep ?sslmode=require)."
            ) from e
        print(f"[DB] ✅ Connected to {self.db.kind}: {self.db.path}")
        if self.db.kind == "sqlite" and not os.environ.get("DB_PATH") and not backup_channel:
            print("[DB] ℹ️ Data is stored in a local file. If your host resets files on every deploy, "
                  "set DATABASE_URL (a real database) instead. See README.")

    async def close(self):
        if self.db is not None and not getattr(self, "_db_closing", False):
            self._db_closing = True
            backup = self.get_cog("Backup")
            if backup:
                await backup.final_backup()  # needs the Discord connection, so it runs first
        await super().close()
        if self.db is not None:
            await self.db.close()
            self.db = None


# help_command=None because we ship our own, nicer one in commands/helpcmd.py
bot = ScadeBot(command_prefix="!", intents=intents, help_command=None)

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
    "commands.backup",
    "games.pokemon",
    "games.pokebattle",
    "games.pokemarket",
]


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name="with the world Sir Shiny created!"))

    # Load reaction roles data manually
    rr_cog = bot.get_cog("ReactionRoles")
    if rr_cog and not getattr(bot, "_rr_loaded", False):
        bot._rr_loaded = True  # on_ready can fire many times; load only once
        await rr_cog.load_reaction_roles()
    elif not rr_cog:
        print("⚠️ ReactionRoles cog not found. Skipping reaction role loading.")


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
