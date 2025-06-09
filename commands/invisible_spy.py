import discord
from discord.ext import commands

class InvisibleSpy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="invisible_users")
    @commands.is_owner()
    async def invisible_users(self, ctx):
        guild = ctx.guild
        invisibles = []

        for member in guild.members:
            if member.status == discord.Status.invisible and not member.bot:
                invisibles.append(member.display_name)

        if not invisibles:
            await ctx.send("👻 No invisible users found (or they're too sneaky for Discord's API).")
        else:
            user_list = ", ".join(invisibles)
            await ctx.send(f"🔍 Invisible users: {user_list}")

async def setup(bot):
    await bot.add_cog(InvisibleSpy(bot))
