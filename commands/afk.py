import time

import discord
from discord.ext import commands


class AFK(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.afk_users = {}  # user_id -> (reason, since)  (cache of the database table)

    async def cog_load(self):
        rows = await self.bot.db.fetchall("SELECT user_id, reason, since FROM afk")
        self.afk_users = {r["user_id"]: (r["reason"], r["since"]) for r in rows}

    async def _clear(self, user_id):
        self.afk_users.pop(user_id, None)
        await self.bot.db.execute("DELETE FROM afk WHERE user_id = ?", (user_id,))

    @commands.command()
    async def afk(self, ctx, *, reason: str = "AFK"):
        reason = reason[:200]
        since = int(time.time())
        self.afk_users[ctx.author.id] = (reason, since)
        await self.bot.db.execute(
            "INSERT INTO afk (user_id, reason, since) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET reason = excluded.reason, since = excluded.since",
            (ctx.author.id, reason, since),
        )
        await ctx.send(
            f"🛌 {ctx.author.mention} is now AFK: *{reason}*",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        # Clear AFK if user was AFK
        if message.author.id in self.afk_users and not message.content.startswith("!afk"):
            await self._clear(message.author.id)
            try:
                await message.channel.send(
                    f"👋 Welcome back, {message.author.mention}. I removed your AFK status.", delete_after=5
                )
            except discord.Forbidden:
                pass  # If bot can't send messages

        # Check mentions for AFK users
        for user in message.mentions:
            if user.id in self.afk_users:
                reason, since = self.afk_users[user.id]
                try:
                    await message.channel.send(
                        f"📢 {user.display_name} is AFK: *{reason}* (since <t:{since}:R>)",
                        delete_after=10,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.Forbidden:
                    pass


async def setup(bot):
    await bot.add_cog(AFK(bot))
