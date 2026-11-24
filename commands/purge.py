import time

import discord
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

    # --------------------- WARN (saved in the database) ---------------------
    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason="No reason provided"):
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, member.id, ctx.author.id, reason[:500], int(time.time())),
        )
        self.bot.dispatch("scade_data_changed")
        await ctx.send(f"⚠️ {member.mention} was warned. Reason: {reason}")

    @commands.command()
    async def warnings(self, ctx, member: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT reason, created_at FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id",
            (ctx.guild.id, member.id),
        )
        if rows:
            warn_list = "\n".join(
                f"{i + 1}. {r['reason']} (<t:{r['created_at']}:R>)" for i, r in enumerate(rows)
            )
            await ctx.send(f"📋 {member.mention} has {len(rows)} warning(s):\n{warn_list}"[:2000])
        else:
            await ctx.send(f"✅ {member.mention} has no warnings.")

    @commands.command(name="delwarn")
    @commands.has_permissions(manage_messages=True)
    async def delwarn(self, ctx, member: discord.Member, number: int):
        """Remove one warning (use the number shown by !warnings)."""
        rows = await self.bot.db.fetchall(
            "SELECT id FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id", (ctx.guild.id, member.id)
        )
        if not 1 <= number <= len(rows):
            return await ctx.send(f"❌ {member.display_name} has {len(rows)} warning(s); pick a number from 1 to {len(rows)}.")
        await self.bot.db.execute("DELETE FROM warnings WHERE id = ?", (rows[number - 1]["id"],))
        self.bot.dispatch("scade_data_changed")
        await ctx.send(f"🗑️ Removed warning #{number} from {member.mention}.")

    @commands.command(name="clearwarns")
    @commands.has_permissions(manage_messages=True)
    async def clearwarns(self, ctx, member: discord.Member):
        """Remove ALL warnings from a member."""
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, member.id)
        )
        self.bot.dispatch("scade_data_changed")
        await ctx.send(f"🧽 Cleared all warnings for {member.mention}.")

async def setup(bot):
    await bot.add_cog(Moderation(bot))
