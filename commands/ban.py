import discord
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.warns = {}  # Simple in-memory warning tracker

    @commands.command(name='ban')
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.ban(reason=reason)
        await ctx.send(f"{member.mention} has been banned. Reason: {reason}")

    @commands.command(name='mute')
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not muted_role:
            muted_role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                await channel.set_permissions(muted_role, send_messages=False, speak=False)
        await member.add_roles(muted_role)
        await ctx.send(f"{member.mention} has been muted. Reason: {reason}")

    @commands.command(name='unmute')
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if muted_role in member.roles:
            await member.remove_roles(muted_role)
            await ctx.send(f"{member.mention} has been unmuted.")
        else:
            await ctx.send("This user is not muted.")

    @commands.command(name='warn')
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason="No reason provided"):
        self.warns.setdefault(member.id, []).append(reason)
        await ctx.send(f"{member.mention} has been warned. Reason: {reason}")

    @commands.command(name='warnings')
    async def warnings(self, ctx, member: discord.Member):
        warns = self.warns.get(member.id, [])
        if warns:
            await ctx.send(f"{member.mention} has {len(warns)} warning(s):\n" + "\n".join(warns))
        else:
            await ctx.send(f"{member.mention} has no warnings.")

async def setup(bot):
    await bot.add_cog(Moderation(bot))
