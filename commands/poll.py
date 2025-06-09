import discord
from discord.ext import commands

class PollView(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=None)
        self.votes = {label: 0 for label in options}

        for label in options:
            self.add_item(PollButton(label, self))

class PollButton(discord.ui.Button):
    def __init__(self, label, view):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.view = view

    async def callback(self, interaction: discord.Interaction):
        self.view.votes[self.label] += 1
        await interaction.response.send_message(
            f"🗳️ You voted for **{self.label}**!", ephemeral=True
        )

class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="poll")
    async def poll(self, ctx, question: str, *options: str):
        if len(options) < 2:
            await ctx.send("❌ You need at least 2 options.")
            return
        if len(options) > 5:
            await ctx.send("⚠️ You can provide up to 5 options.")
            return

        embed = discord.Embed(
            title="📊 Poll",
            description=question,
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Click a button below to vote!")
        await ctx.send(embed=embed, view=PollView(options))

async def setup(bot):
    await bot.add_cog(Polls(bot))
