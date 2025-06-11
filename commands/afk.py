import discord
from discord.ext import commands

class AFK(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.afk_users = {}  # user_id -> reason

    @commands.command()
    async def afk(self, ctx, *, reason: str = "AFK"):
        self.afk_users[ctx.author.id] = reason
        await ctx.send(f"🛌 {ctx.author.mention} is now AFK: *{reason}*")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        # Clear AFK if user was AFK
        if message.author.id in self.afk_users and not message.content.startswith("!afk"):
            del self.afk_users[message.author.id]
            try:
                await message.channel.send(f"👋 Welcome back, {message.author.mention}. I removed your AFK status.", delete_after=5)
            except discord.Forbidden:
                pass  # If bot can't send messages

        # Check mentions for AFK users
        for user in message.mentions:
            if user.id in self.afk_users:
                reason = self.afk_users[user.id]
                await message.channel.send(f"📢 {user.display_name} is AFK: *{reason}*", delete_after=10)

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if before.status != after.status and after.status == discord.Status.online:
            if after.id in self.afk_users:
                del self.afk_users[after.id]
                try:
                    channel = discord.utils.get(after.mutual_guilds[0].text_channels, permissions__send_messages=True)
                    if channel:
                        await channel.send(f"👋 {after.display_name} is back online. AFK status cleared.")
                except:
                    pass  # Skip if channel not found or can't send

async def setup(bot):
    await bot.add_cog(AFK(bot))
