import json
import os
import time

from discord.ext import commands

# Only used ONCE: the old keys in this file are imported into the database the first
# time the bot starts. After that the database is the source of truth.
LEGACY_JSON = os.path.join(os.path.dirname(__file__), "recall_messages.json")
MAX_LEN = 2000  # Discord message limit


def split_chunks(text: str, limit: int = 1900):
    chunks, current = [], ""
    for part in text.split(", "):
        if len(current) + len(part) + 2 > limit and current:
            chunks.append(current)
            current = ""
        current = f"{current}, {part}" if current else part
    if current:
        chunks.append(current)
    return chunks


class Recall(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self._import_legacy_json()

    async def _import_legacy_json(self):
        db = self.bot.db
        if await db.meta_get("imported_recall_json"):
            return
        imported = 0
        if os.path.exists(LEGACY_JSON):
            try:
                with open(LEGACY_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = int(time.time())

                def work(conn):
                    n = 0
                    for key, message in data.items():
                        cur = conn.execute(
                            "INSERT OR IGNORE INTO recalls (guild_id, key, message, created_at) VALUES (0, ?, ?, ?)",
                            (str(key).lower(), str(message), now),
                        )
                        n += cur.rowcount
                    return n

                imported = await db.transaction(work)
            except Exception as e:  # noqa: BLE001
                print(f"[Recall] Couldn't import {LEGACY_JSON}: {type(e).__name__}: {e}")
                return  # try again next start
        await db.meta_set("imported_recall_json", "1")
        print(f"[Recall] Imported {imported} recall message(s) from the old JSON file.")

    # ------------------------------------------------------------ helpers
    async def _find(self, guild_id, key):
        # A server's own key wins over a global (guild 0) key
        return await self.bot.db.fetchone(
            "SELECT * FROM recalls WHERE key = ? AND guild_id IN (?, 0) ORDER BY guild_id DESC LIMIT 1",
            (key, guild_id),
        )

    # ----------------------------------------------------------- commands
    @commands.command(name="recall")
    async def recall(self, ctx, key: str = None):
        if not key:
            return await ctx.send("❌ Please provide a key. Usage: `!recall <key>`")
        row = await self._find(ctx.guild.id if ctx.guild else 0, key.lower())
        if row:
            await ctx.send(row["message"])
        else:
            await ctx.send(f"❌ No message found for key: `{key.lower()}`")

    @commands.command(name="setrecall")
    @commands.has_permissions(administrator=True)
    async def setrecall(self, ctx, key: str, *, message: str):
        key = key.lower()
        if len(message) > MAX_LEN:
            return await ctx.send(f"❌ That message is too long ({len(message)}/{MAX_LEN} characters).")
        guild_id = ctx.guild.id if ctx.guild else 0
        existed = await self.bot.db.fetchone(
            "SELECT 1 FROM recalls WHERE guild_id = ? AND key = ?", (guild_id, key)
        )
        await self.bot.db.execute(
            "INSERT INTO recalls (guild_id, key, message, created_by, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET message = excluded.message, "
            "created_by = excluded.created_by, created_at = excluded.created_at",
            (guild_id, key, message, ctx.author.id, int(time.time())),
        )
        self.bot.dispatch("scade_data_changed")
        await ctx.send(f"✅ {'Updated' if existed else 'Set'} recall message for `{key}`.")

    @commands.command(name="delrecall")
    @commands.has_permissions(administrator=True)
    async def delrecall(self, ctx, key: str):
        key = key.lower()
        guild_id = ctx.guild.id if ctx.guild else 0

        def work(conn):
            n = conn.execute("DELETE FROM recalls WHERE guild_id = ? AND key = ?", (guild_id, key)).rowcount
            if n == 0:  # maybe it's one of the old global keys
                n = conn.execute("DELETE FROM recalls WHERE guild_id = 0 AND key = ?", (key,)).rowcount
            return n

        deleted = await self.bot.db.transaction(work)
        if deleted:
            self.bot.dispatch("scade_data_changed")
            await ctx.send(f"🗑️ Deleted recall message for `{key}`.")
        else:
            await ctx.send(f"❌ No recall message found for `{key}`.")

    @commands.command(name="listrecall")
    async def listrecall(self, ctx):
        guild_id = ctx.guild.id if ctx.guild else 0
        rows = await self.bot.db.fetchall(
            "SELECT DISTINCT key FROM recalls WHERE guild_id IN (?, 0) ORDER BY key", (guild_id,)
        )
        if not rows:
            return await ctx.send("No recall messages have been set.")
        keys = ", ".join(r["key"] for r in rows)
        for i, chunk in enumerate(split_chunks(keys)):
            title = "📚 Available keys" if i == 0 else "📚 …continued"
            await ctx.send(f"{title}: `{chunk}`")


async def setup(bot):
    await bot.add_cog(Recall(bot))
