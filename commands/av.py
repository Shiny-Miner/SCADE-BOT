import discord
from discord.ext import commands

class Avatar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="av")
    async def avatar(self, ctx, *, user: discord.User = None):
        """Shows avatar of yourself or a mentioned user."""
        user = user or ctx.author  # Default to message author if no user is mentioned
        embed = discord.Embed(title=f"{user.name}'s Avatar", color=discord.Color.blurple())
        embed.set_image(url=user.avatar.url if user.avatar else user.default_avatar.url)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Avatar(bot))
