from discord.ext import commands

class AhResponder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        content = message.content.strip()
        if content in ["ah", "Ah", "AH"]:
            await message.channel.send("CHOO!")

async def setup(bot):
    await bot.add_cog(AhResponder(bot))
