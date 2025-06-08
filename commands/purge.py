
import discord
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        if amount < 1:
            await ctx.send("🚫 Please enter a number greater than 0.", delete_after=5)
            return
        deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to also delete the command message
        await ctx.send(f"✅ Deleted {len(deleted)-1} message(s).", delete_after=3)

    @purge.error
    async def purge_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don’t have permission to use this command.", delete_after=5)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❗ Usage: `!purge <number>`", delete_after=5)
        else:
            raise error

async def setup(bot):
    await bot.add_cog(Moderation(bot))
