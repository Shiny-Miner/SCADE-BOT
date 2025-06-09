import discord
from discord.ext import commands, tasks
import datetime

# Set your channel ID here
SHOWOFF_CHANNEL_ID = 1129058688963973211  # Replace with your actual channel ID

class ShowoffSunday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_sunday_event.start()

    def cog_unload(self):
        self.check_sunday_event.cancel()

    @tasks.loop(minutes=1)
    async def check_sunday_event(self):
        now = datetime.datetime.utcnow()

        if now.weekday() == 6 and now.hour == 0 and now.minute == 0:  # Sunday 00:00 UTC
            await self.unlock_channel()

        if now.weekday() == 0 and now.hour == 0 and now.minute == 0:  # Monday 00:00 UTC
            await self.lock_channel()

    async def unlock_channel(self):
        channel = self.bot.get_channel(SHOWOFF_CHANNEL_ID)
        if channel is None:
            return

        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = True
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)

        await channel.send("@here 🎉 **Showoff Sunday** opens its gates!")

    async def lock_channel(self):
        channel = self.bot.get_channel(SHOWOFF_CHANNEL_ID)
        if channel is None:
            return

        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)

        await channel.send("🔒 **Showoff Sunday** has ended. Channel is now locked.")

    @check_sunday_event.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(ShowoffSunday(bot))
