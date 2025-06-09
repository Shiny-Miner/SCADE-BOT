import discord
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.warns = {}

    # --------------------- PURGE ---------------------
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        if amount < 1:
            await ctx.send("🚫 Please enter a number greater than 0.", delete_after=5)
            return
        deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to delete the command too
        await ctx.send(f"✅ Deleted {len(deleted)-1} message(s).", delete_after=3)

    @purge.error
    async def purge_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don’t have permission to use this command.", delete_after=5)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❗ Usage: `!purge <number>`", delete_after=5)
        else:
            raise error

    # --------------------- BAN ---------------------
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.ban(reason=reason)
        await ctx.send(f"🔨 {member.mention} was banned. Reason: {reason}")

    # --------------------- KICK ---------------------
    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member.mention} was kicked. Reason: {reason}")

    # --------------------- SOFTBAN ---------------------
    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def softban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await member.ban(reason=reason, delete_message_days=1)
        await member.unban(reason="Softban reversal")
        await ctx.send(f"🧹 {member.mention} was softbanned. Recent messages deleted and user removed.")

    # --------------------- MUTE ---------------------
    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, *, reason="No reason provided"):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not muted_role:
            muted_role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                await channel.set_permissions(muted_role, send_messages=False, speak=False)
        await member.add_roles(muted_role)
        await ctx.send(f"🔇 {member.mention} was muted. Reason: {reason}")

    # --------------------- UNMUTE ---------------------
    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if muted_role and muted_role in member.roles:
            await member.remove_roles(muted_role)
            await ctx.send(f"🔊 {member.mention} was unmuted.")
        else:
            await ctx.send("❌ This user is not muted.")

    # --------------------- WARN ---------------------
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason="No reason provided"):
        self.warns.setdefault(member.id, []).append(reason)
        await ctx.send(f"⚠️ {member.mention} was warned. Reason: {reason}")

    @commands.command()
    async def warnings(self, ctx, member: discord.Member):
        warns = self.warns.get(member.id, [])
        if warns:
            warn_list = "\n".join(f"{i+1}. {w}" for i, w in enumerate(warns))
            await ctx.send(f"📋 {member.mention} has {len(warns)} warning(s):\n{warn_list}")
        else:
            await ctx.send(f"✅ {member.mention} has no warnings.")

async def setup(bot):
    await bot.add_cog(Moderation(bot))
