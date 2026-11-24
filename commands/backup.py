import asyncio
import io
import os
import tempfile
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from database import BACKUP_PREFIX, compress_file, decompress_if_needed, validate_sqlite_bytes

KEEP_BACKUPS = 24          # how many backup messages to keep in the channel
AUTO_BACKUP_MINUTES = 30   # periodic backup (only uploads if something changed)
CHANGE_DELAY_SECONDS = 45  # after an important change (recall, reaction role...) back up soon


def backup_channel_id():
    raw = os.environ.get("BACKUP_CHANNEL_ID", "").strip()
    return int(raw) if raw.isdigit() else None


class Backup(commands.Cog):
    """Keeps the database safe even when the host wipes its disk on every deploy."""

    def __init__(self, bot):
        self.bot = bot
        self.last_changes = None
        self.last_backup_at = None
        self._debounce = None
        self._backup_lock = asyncio.Lock()

    # ------------------------------------------------------------ lifecycle
    @property
    def is_sqlite(self):
        return getattr(self.bot.db, "kind", "sqlite") == "sqlite"

    async def cog_load(self):
        if not self.is_sqlite:
            print("[Backup] Using a hosted PostgreSQL database: Discord backups are not needed.")
        elif backup_channel_id():
            self.auto_backup.start()
        else:
            print(
                "[Backup] ⚠️ BACKUP_CHANNEL_ID is not set. If your host wipes files on redeploy, "
                "you will lose data! Set DB_PATH to a persistent disk and/or BACKUP_CHANNEL_ID."
            )

    async def cog_unload(self):
        self.auto_backup.cancel()
        if self._debounce:
            self._debounce.cancel()

    # ------------------------------------------------------------- core logic
    async def make_backup(self, reason="manual", only_if_changed=False, force=False):
        """Upload a compressed snapshot to the backup channel. Returns a status string."""
        channel_id = backup_channel_id()
        if not self.is_sqlite:
            return "not_needed"
        if not channel_id:
            return "no_channel"
        blocked = getattr(self.bot, "backup_blocked", None)
        if blocked and not force:
            return f"blocked: {blocked}"

        async with self._backup_lock:
            db = self.bot.db
            changes = db.total_changes
            if only_if_changed and self.last_changes is not None and changes == self.last_changes:
                return "unchanged"

            tmp_dir = tempfile.mkdtemp(prefix="scade-bk-")
            snap = os.path.join(tmp_dir, "snapshot.db")
            try:
                await asyncio.to_thread(db.snapshot, snap)
                data = await asyncio.to_thread(compress_file, snap)
            finally:
                try:
                    os.remove(snap)
                    os.rmdir(tmp_dir)
                except OSError:
                    pass

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            filename = f"{BACKUP_PREFIX}-{stamp}.db.gz"
            try:
                channel = await self.bot.fetch_channel(channel_id)
                await channel.send(
                    f"💾 Database backup ({reason}) • {len(data) / 1024:.0f} KB",
                    file=discord.File(io.BytesIO(data), filename=filename),
                )
            except discord.HTTPException as e:
                print(f"[Backup] ❌ Upload failed: {e}")
                return f"failed: {e}"

            self.last_changes = changes
            self.last_backup_at = int(time.time())
            if force and blocked:
                self.bot.backup_blocked = None
            await self._prune(channel)
            return "ok"

    async def _prune(self, channel):
        try:
            mine = []
            async for msg in channel.history(limit=200):
                if msg.author.id == self.bot.user.id and any(
                    a.filename.startswith(BACKUP_PREFIX) for a in msg.attachments
                ):
                    mine.append(msg)
            for old in mine[KEEP_BACKUPS:]:
                await old.delete()
        except discord.HTTPException as e:
            print(f"[Backup] Could not prune old backups: {e}")

    async def final_backup(self):
        """Called by bot.close() so a redeploy doesn't lose the last few minutes."""
        try:
            await asyncio.wait_for(self.make_backup("shutdown", only_if_changed=True), timeout=15)
        except Exception as e:  # noqa: BLE001
            print(f"[Backup] Shutdown backup skipped: {type(e).__name__}: {e}")

    # ----------------------------------------------------------- scheduling
    @tasks.loop(minutes=AUTO_BACKUP_MINUTES)
    async def auto_backup(self):
        try:
            await self.make_backup("auto", only_if_changed=True)
        except Exception as e:  # noqa: BLE001
            print(f"[Backup] auto backup error: {type(e).__name__}: {e}")

    @auto_backup.before_loop
    async def before_auto(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_scade_data_changed(self):
        """Other cogs call bot.dispatch('scade_data_changed') after important edits."""
        if not self.is_sqlite or not backup_channel_id() or (self._debounce and not self._debounce.done()):
            return

        async def later():
            await asyncio.sleep(CHANGE_DELAY_SECONDS)
            await self.make_backup("change", only_if_changed=True)

        self._debounce = asyncio.create_task(later())

    # ------------------------------------------------------------- commands
    @commands.command(name="dbstatus", help="Show where the database lives and what is stored. (Owner)")
    @commands.is_owner()
    async def dbstatus(self, ctx):
        db = self.bot.db
        counts = await db.table_counts()
        embed = discord.Embed(title="🗄️ Database status", color=discord.Color.blurple())
        if self.is_sqlite:
            size = os.path.getsize(db.path) / 1024 if os.path.exists(db.path) else 0
            embed.add_field(name="SQLite file", value=f"`{db.path}`\n{size:.0f} KB", inline=False)
        else:
            embed.add_field(name="PostgreSQL", value=f"`{db.path}`", inline=False)
        embed.add_field(name="Stored", value="\n".join(f"**{k}**: {v}" for k, v in counts.items()), inline=True)
        if not self.is_sqlite:
            embed.set_footer(text="✅ Real hosted database: your provider keeps it between deploys.")
            return await ctx.send(embed=embed)
        ch = backup_channel_id()
        backup_text = f"Channel: <#{ch}>" if ch else "❌ `BACKUP_CHANNEL_ID` not set"
        if self.last_backup_at:
            backup_text += f"\nLast backup: <t:{self.last_backup_at}:R>"
        blocked = getattr(self.bot, "backup_blocked", None)
        if blocked:
            backup_text += f"\n⛔ Auto-backups paused: {blocked}\nUse `!backup force` once you've checked everything."
        embed.add_field(name="Discord backups", value=backup_text, inline=True)
        if not os.environ.get("DB_PATH"):
            embed.set_footer(text="Tip: set DB_PATH to a persistent disk so redeploys never wipe the file.")
        await ctx.send(embed=embed)

    @commands.command(name="backup", usage="[force]", help="Make a database backup right now. (Owner)")
    @commands.is_owner()
    async def backup(self, ctx, mode: str = None):
        if not self.is_sqlite:
            return await ctx.send("✅ You're on a hosted PostgreSQL database. Your provider handles backups (see its dashboard), so this command isn't needed.")
        force = (mode or "").lower() == "force"
        async with ctx.typing():
            status = await self.make_backup("manual", force=force)
            # Always DM a copy to the owner too, so it works without a backup channel
            tmp_dir = tempfile.mkdtemp(prefix="scade-bk-")
            snap = os.path.join(tmp_dir, "snapshot.db")
            try:
                await asyncio.to_thread(self.bot.db.snapshot, snap)
                data = await asyncio.to_thread(compress_file, snap)
            finally:
                try:
                    os.remove(snap)
                    os.rmdir(tmp_dir)
                except OSError:
                    pass
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        try:
            await ctx.author.send(
                "Here is a copy of the database. Restore it with `!restore confirm` + this file attached.",
                file=discord.File(io.BytesIO(data), filename=f"{BACKUP_PREFIX}-{stamp}.db.gz"),
            )
            dm = "📬 I DM'd you a copy."
        except discord.HTTPException:
            dm = "⚠️ I couldn't DM you (DMs closed, or the file is too big)."
        channel_note = {
            "ok": "☁️ Uploaded to the backup channel.",
            "no_channel": "ℹ️ No `BACKUP_CHANNEL_ID` configured.",
        }.get(status, f"⚠️ Backup channel: {status}")
        await ctx.send(f"{dm}\n{channel_note}")

    @commands.command(name="restore", usage="confirm  (attach a backup file)", help="Restore a database backup. (Owner)")
    @commands.is_owner()
    async def restore(self, ctx, confirm: str = None):
        if not self.is_sqlite:
            return await ctx.send("❌ `!restore` is for the local SQLite file only. With PostgreSQL, restore from your provider's dashboard.")
        if (confirm or "").lower() != "confirm" or not ctx.message.attachments:
            return await ctx.send(
                "⚠️ This **replaces all current data** with the backup.\n"
                "Attach a `scade-backup-….db.gz` (or `.db`) file and run `!restore confirm`."
            )
        att = ctx.message.attachments[0]
        if att.size > 25 * 1024 * 1024:
            return await ctx.send("❌ That file is too big.")
        raw = await att.read()
        try:
            data = decompress_if_needed(raw)
        except Exception:  # noqa: BLE001
            return await ctx.send("❌ I couldn't unpack that file.")
        tmp = os.path.join(tempfile.gettempdir(), "scade-restore-check.db")
        ok = await asyncio.to_thread(validate_sqlite_bytes, data, tmp)
        if not ok:
            return await ctx.send("❌ That file isn't a healthy SCADE database.")
        await asyncio.to_thread(self.bot.db.restore_from_file, tmp)
        for ext in ("commands.rr", "commands.afk"):
            try:
                await self.bot.reload_extension(ext)
            except Exception as e:  # noqa: BLE001
                print(f"[Restore] reload {ext} failed: {e}")
        self.bot.backup_blocked = None
        await ctx.send(
            "✅ Database restored. Reaction roles and AFK were reloaded. "
            "Restart the bot to also revive polls that were open in the backup."
        )


async def setup(bot):
    await bot.add_cog(Backup(bot))
