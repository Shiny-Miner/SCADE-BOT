import discord
from discord.ext import commands, tasks
import asyncio

class PollView(discord.ui.View):
    def __init__(self, options, duration, ctx, question):
        super().__init__(timeout=duration)
        self.ctx = ctx
        self.question = question
        self.options = options
        self.vote_counts = {label: 0 for label in options}
        self.voters = {}  # user_id -> choice label

        for label in options:
            self.add_item(PollOptionButton(label, self))

    async def on_timeout(self):
        results = sorted(self.vote_counts.items(), key=lambda x: x[1], reverse=True)
        result_text = "\n".join(f"**{label}** — {count} vote(s)" for label, count in results)

        result_embed = discord.Embed(
            title="🗳️ Poll Closed!",
            description=f"**{self.question}**\n\n{result_text}",
            color=discord.Color.green()
        )
        await self.ctx.send(embed=result_embed)

class PollOptionButton(discord.ui.Button):
    def __init__(self, label, view: PollView):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.poll_view = view

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id in self.poll_view.voters:
            prev = self.poll_view.voters[user_id]
            await interaction.response.send_message(
                f"❌ You already voted for **{prev}**!", ephemeral=True
            )
            return

        self.poll_view.voters[user_id] = self.label
        self.poll_view.vote_counts[self.label] += 1
        await interaction.response.send_message(
            f"✅ You voted for **{self.label}**!", ephemeral=True
        )

class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="poll")
    async def poll(self, ctx, duration: int, question: str, *options: str):
        """Starts a timed poll.
        Usage: !poll <duration_seconds> "Question" "Option 1" "Option 2" ...
        """
        if len(options) < 2:
            await ctx.send("❌ You need at least 2 options.")
            return
        if len(options) > 5:
            await ctx.send("⚠️ You can provide up to 5 options.")
            return

        embed = discord.Embed(
            title="📊 Poll Started!",
            description=question,
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Poll closes in {duration} seconds. Click a button to vote!")

        view = PollView(options, duration, ctx, question)
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Polls(bot))
