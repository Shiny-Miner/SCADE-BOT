import discord
from discord.ext import commands
from discord.ext import commands
import discord

class Welcomer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.welcome_channel_id = 1378218632672444510  # Change this if you want to hardcode

    def get_fallback_channel(self, guild: discord.Guild):
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                return channel
        return None

    @commands.Cog.listener()
    async def on_member_join(self, member):
        print(f"[Welcomer] on_member_join called for {member.name}")  # DEBUG

        channel = self.bot.get_channel(self.welcome_channel_id) if self.welcome_channel_id else None
        if channel is None:
            channel = self.get_fallback_channel(member.guild)

        if channel:
            member_count = member.guild.member_count
            embed = discord.Embed(
                title="👋 Welcome!",
                description=f"Welcome to the server, {member.mention}! 🎉\nYou're member **#{member_count}**!",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        print(f"[Welcomer] {member.name} left {member.guild.name}")  # Debug log

        channel = self.bot.get_channel(self.welcome_channel_id) or self.get_fallback_channel(member.guild)
        if channel:
            embed = discord.Embed(
                title="😢 Member Left",
                description=f"`{member.name}` has left the server.\nWe now have **{member.guild.member_count}** members.",
                color=discord.Color.red()
            )
            await channel.send(embed=embed)

    @commands.command()
    async def test_leave(self, ctx):
        member = ctx.guild.get_member(ctx.author.id)
        if member:
            await self.on_member_remove(member)

    @commands.command()
    async def test_welcome(self, ctx):
        member = ctx.guild.get_member(ctx.author.id)
        if member:
            await self.on_member_join(member)
        else:
            await ctx.send("❌ Could not find your member object in this server.")

async def setup(bot):
    await bot.add_cog(Welcomer(bot))
