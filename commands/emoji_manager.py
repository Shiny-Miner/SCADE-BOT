import discord
from discord.ext import commands
import aiohttp

class EmojiManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="emoji_add")
    @commands.has_permissions(manage_emojis=True)
    async def emoji_add(self, ctx, emoji_id: int):
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return await ctx.send("❌ Failed to fetch emoji.")
                    data = await resp.read()
            emoji = await ctx.guild.create_custom_emoji(name=f"emoji_{emoji_id}", image=data)
            await ctx.send(f"✅ Added emoji: <:{emoji.name}:{emoji.id}>")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to add emojis.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @commands.command(name="emoji_remove")
    @commands.has_permissions(manage_emojis=True)
    async def emoji_remove(self, ctx, emoji_id: int):
        emoji = discord.utils.get(ctx.guild.emojis, id=emoji_id)
        if emoji:
            try:
                await emoji.delete()
                await ctx.send(f"✅ Removed emoji with ID: {emoji_id}")
            except discord.Forbidden:
                await ctx.send("❌ I don't have permission to delete emojis.")
        else:
            await ctx.send("❌ Emoji not found in this server.")

async def setup(bot):
    await bot.add_cog(EmojiManager(bot))
