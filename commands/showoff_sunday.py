import datetime
import traceback

import discord
from discord.ext import commands, tasks

# Set your channel ID here
SHOWOFF_CHANNEL_ID = 1129058688963973211

UTC = datetime.timezone.utc


class ShowoffSunday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_state = None  # "open" / "closed" – remembers what we already did
        self.check_sunday_event.start()

    def cog_unload(self):
        self.check_sunday_event.cancel()

    async def get_channel(self):
        channel = self.bot.get_channel(SHOWOFF_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(SHOWOFF_CHANNEL_ID)
            except discord.HTTPException as e:
                print(f"[Showoff] Can't find channel {SHOWOFF_CHANNEL_ID}: {e}")
        return channel

    # Runs every 5 minutes and compares the *current state* (is it Sunday?)
    # with what the channel currently is, so a missed minute or a restart
    # no longer skips the event.
    @tasks.loop(minutes=5)
    async def check_sunday_event(self):
        try:
            is_sunday = datetime.datetime.now(UTC).weekday() == 6  # Sunday (UTC)
            channel = await self.get_channel()
            if channel is None:
                return

            everyone = channel.guild.default_role
            currently_open = channel.overwrites_for(everyone).send_messages is True

            if is_sunday and not currently_open:
                await self.set_open(channel, everyone, True)
            elif not is_sunday and currently_open:
                await self.set_open(channel, everyone, False)
        except Exception:
            # Never let the loop die silently
            print("[Showoff] Error in check_sunday_event:")
            traceback.print_exc()

    async def set_open(self, channel, everyone, opened: bool):
        overwrite = channel.overwrites_for(everyone)
        overwrite.send_messages = True if opened else False
        try:
            await channel.set_permissions(everyone, overwrite=overwrite, reason="Showoff Sunday")
        except discord.Forbidden:
            print("[Showoff] ❌ Missing 'Manage Channel/Permissions' for the showoff channel!")
            return
        if opened:
            await channel.send(
                "@here 🎉 **Showoff Sunday** opens its gates!",
                allowed_mentions=discord.AllowedMentions(everyone=True),
            )
        else:
            await channel.send("🔒 **Showoff Sunday** has ended. Channel is now locked.")

    @check_sunday_event.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    @commands.command(name="showoff_test")
    @commands.has_permissions(administrator=True)
    async def showoff_test(self, ctx):
        """Admin: checks that the bot can see/edit the Showoff channel."""
        channel = await self.get_channel()
        if channel is None:
            return await ctx.send("❌ I can't find the showoff channel. Check `SHOWOFF_CHANNEL_ID`.")
        perms = channel.permissions_for(channel.guild.me)
        await ctx.send(
            f"Channel: {channel.mention}\n"
            f"Send messages: {perms.send_messages} | Manage channel: {perms.manage_channels} | "
            f"Manage roles/perms: {perms.manage_roles} | Mention everyone: {perms.mention_everyone}"
        )


async def setup(bot):
    await bot.add_cog(ShowoffSunday(bot))
