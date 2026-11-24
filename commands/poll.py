import asyncio
import json
import re
import secrets
import shlex
import time

import discord
from discord.ext import commands

DEFAULT_DURATION = 60          # seconds, when the user doesn't give a time
MIN_DURATION = 10              # seconds
MAX_DURATION = 7 * 24 * 60 * 60  # 7 days (polls survive restarts, so long polls are safe)
MAX_OPTIONS = 10

POLL_USAGE = (
    "`!poll [time] <question> | <option 1> | <option 2> | ...`\n"
    "`!poll [time] \"Question\" \"Option 1\" \"Option 2\"`\n"
    "`!poll [time] <question>` → quick 👍 / 👎 poll"
)
POLL_EXAMPLES = (
    "`!poll 2m Best editor? | VS Code | Vim | Notepad`\n"
    "`!poll 30 \"Tabs or spaces?\" \"Tabs\" \"Spaces\"`\n"
    "`!poll Is pineapple pizza legal?`"
)

_DURATION_RE = re.compile(r"^(\d+)([smhd]?)$", re.IGNORECASE)
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(token: str):
    """'90' / '90s' / '5m' / '2h' -> seconds, or None if it isn't a duration."""
    m = _DURATION_RE.match(token.strip())
    if not m:
        return None
    return int(m.group(1)) * _UNITS[m.group(2).lower()]


def format_duration(seconds: int) -> str:
    if seconds % 86400 == 0 and seconds >= 86400:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0 and seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0 and seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def parse_poll_args(raw: str):
    """
    Turn the raw text after `!poll` into (duration_seconds, question, options).
    Raises ValueError with a friendly message when the input can't be used.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("You didn't tell me what to ask!")

    # Optional leading duration: "60", "90s", "5m", "2h"
    duration = DEFAULT_DURATION
    first, _, rest = raw.partition(" ")
    parsed = parse_duration(first)
    if parsed is not None and rest.strip():
        duration, raw = parsed, rest.strip()

    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise ValueError(
            f"Poll time must be between **{MIN_DURATION}s** and **7d** "
            f"(you gave {format_duration(duration)})."
        )

    # Normalise "smart quotes" that phones love to insert
    raw = raw.replace("“", '"').replace("”", '"')

    if "|" in raw:
        parts = [p.strip() for p in raw.split("|") if p.strip()]
    elif '"' in raw:
        try:
            parts = [p.strip() for p in shlex.split(raw) if p.strip()]
        except ValueError:
            raise ValueError("I couldn't read your quotes — make sure every `\"` has a closing `\"`.")
    else:
        parts = [raw]

    if not parts:
        raise ValueError("You didn't tell me what to ask!")

    question, options = parts[0], parts[1:]

    if not options:  # just a question -> yes/no poll
        options = ["👍 Yes", "👎 No"]

    # Remove duplicate options (case-insensitive) while keeping order
    seen, unique = set(), []
    for opt in options:
        key = opt.lower()
        if key not in seen:
            seen.add(key)
            unique.append(opt)
    options = unique

    if len(options) < 2:
        raise ValueError("I need at least **2 different options**.")
    if len(options) > MAX_OPTIONS:
        raise ValueError(f"That's too many options — the limit is **{MAX_OPTIONS}**.")
    if len(question) > 300:
        raise ValueError("That question is too long (max 300 characters).")

    options = [o[:80] for o in options]  # Discord button labels max out at 80 chars
    return duration, question, options


class PollButton(discord.ui.Button):
    def __init__(self, token: str, index: int, label: str):
        # A fixed custom_id is what lets the button keep working after a bot restart
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"poll:{token}:{index}")
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: "PollView" = self.view
        if view.closed:
            return await interaction.response.send_message("🔒 This poll has already closed.", ephemeral=True)

        previous = view.votes.get(interaction.user.id)
        if previous == self.index:
            return await interaction.response.send_message(
                f"You already voted for **{self.label}** 😉", ephemeral=True
            )

        view.votes[interaction.user.id] = self.index
        await view.bot.db.execute(
            "INSERT INTO poll_votes (token, user_id, option_index) VALUES (?, ?, ?) "
            "ON CONFLICT(token, user_id) DO UPDATE SET option_index = excluded.option_index",
            (view.token, interaction.user.id, self.index),
        )
        # Update the poll message live, which also acknowledges the click
        await interaction.response.edit_message(embed=view.build_embed(), view=view)
        note = "changed your vote to" if previous is not None else "voted for"
        await interaction.followup.send(f"✅ You {note} **{self.label}**!", ephemeral=True)


class PollView(discord.ui.View):
    def __init__(self, bot, token, author_name, question, options, ends_at, votes=None):
        # timeout=None: required for persistent views. We run our own timer instead.
        super().__init__(timeout=None)
        self.bot = bot
        self.token = token
        self.author_name = author_name
        self.question = question
        self.options = options
        self.ends_at = int(ends_at)  # unix seconds
        self.votes = votes or {}  # user_id -> option index
        self.closed = False
        self.message = None
        self._timer = None

        for i, label in enumerate(options):
            self.add_item(PollButton(token, i, label))

    def counts(self):
        counts = [0] * len(self.options)
        for idx in self.votes.values():
            if 0 <= idx < len(counts):
                counts[idx] += 1
        return counts

    def build_embed(self) -> discord.Embed:
        counts = self.counts()
        total = sum(counts)
        lines = []
        for label, n in zip(self.options, counts):
            pct = (n / total * 100) if total else 0
            filled = round(pct / 10)
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"**{label}**\n`{bar}` {n} vote{'s' if n != 1 else ''} ({pct:.0f}%)")

        if self.closed:
            title, color = "🗳️ Poll Closed", discord.Color.green()
            footer = f"Final result • {total} vote{'s' if total != 1 else ''} • Started by {self.author_name}"
            if total:
                top = max(counts)
                winners = [o for o, n in zip(self.options, counts) if n == top]
                verdict = (f"🏆 **Winner:** {winners[0]}" if len(winners) == 1
                           else "🤝 **It's a tie:** " + ", ".join(winners))
                lines.append("\n" + verdict)
            else:
                lines.append("\n😴 Nobody voted. Democracy is dead.")
        else:
            title, color = "📊 Poll", discord.Color.blurple()
            footer = f"Started by {self.author_name} • Click a button to vote: you can change your vote"
            lines.append(f"\n⏳ Closes <t:{self.ends_at}:R>")

        embed = discord.Embed(title=title, description=f"### {self.question}\n\n" + "\n\n".join(lines), color=color)
        embed.set_footer(text=footer)
        return embed

    def start_timer(self):
        self._timer = asyncio.create_task(self._close_later())

    async def _close_later(self):
        await asyncio.sleep(max(0, self.ends_at - time.time()))
        await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        for child in self.children:
            child.disabled = True
        self.stop()
        try:
            await self.bot.db.execute("UPDATE polls SET closed = 1 WHERE token = ?", (self.token,))
        except Exception as e:  # noqa: BLE001
            print(f"[Poll] Couldn't mark poll closed: {e}")
        if self.message:
            try:
                await self.message.edit(embed=self.build_embed(), view=self)
            except discord.HTTPException as e:
                print(f"[Poll] Couldn't edit finished poll: {e}")


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.views = []

    async def cog_load(self):
        """Bring polls that were running before a restart back to life."""
        rows = await self.bot.db.fetchall("SELECT * FROM polls WHERE closed = 0")
        for row in rows:
            votes_rows = await self.bot.db.fetchall(
                "SELECT user_id, option_index FROM poll_votes WHERE token = ?", (row["token"],)
            )
            view = PollView(
                self.bot, row["token"], row["author_name"], row["question"], json.loads(row["options"]),
                row["ends_at"], {v["user_id"]: v["option_index"] for v in votes_rows},
            )
            view.channel_id, view.message_id = row["channel_id"], row["message_id"]
            self.bot.add_view(view, message_id=row["message_id"])  # buttons work again right away
            self.views.append(view)
        if self.views:
            print(f"[Polls] Restored {len(self.views)} running poll(s).")
            asyncio.create_task(self._reattach())

    async def cog_unload(self):
        for view in self.views:
            if view._timer:
                view._timer.cancel()

    async def _reattach(self):
        """Once connected: find each poll message and restart its closing timer."""
        await self.bot.wait_until_ready()
        for view in self.views:
            try:
                channel = self.bot.get_channel(view.channel_id) or await self.bot.fetch_channel(view.channel_id)
                view.message = await channel.fetch_message(view.message_id)
            except discord.HTTPException as e:
                print(f"[Polls] Couldn't find poll message {view.message_id}: {e}")
            view.start_timer()  # closes immediately if the time ran out while the bot was offline

    @commands.command(
        name="poll",
        usage="[time] <question> | <option 1> | <option 2> ...",
        help="Start a timed poll with live vote bars.",
    )
    async def poll(self, ctx, *, args: str = None):
        try:
            duration, question, options = parse_poll_args(args)
        except ValueError as e:
            embed = discord.Embed(title="📊 How to use !poll", description=f"❌ {e}", color=discord.Color.red())
            embed.add_field(name="Usage", value=POLL_USAGE, inline=False)
            embed.add_field(name="Examples", value=POLL_EXAMPLES, inline=False)
            embed.add_field(
                name="Time",
                value=f"Optional, e.g. `30`, `90s`, `5m`, `2h`, `3d` (min {MIN_DURATION}s, max 7d, default {DEFAULT_DURATION}s).",
                inline=False,
            )
            return await ctx.send(embed=embed)

        token = secrets.token_hex(6)
        ends_at = int(time.time()) + duration
        view = PollView(self.bot, token, ctx.author.display_name, question, options, ends_at)
        view.message = await ctx.send(embed=view.build_embed(), view=view)
        view.channel_id, view.message_id = ctx.channel.id, view.message.id
        await self.bot.db.execute(
            "INSERT INTO polls (token, message_id, channel_id, guild_id, author_id, author_name, question, options, ends_at, closed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (token, view.message.id, ctx.channel.id, ctx.guild.id if ctx.guild else 0, ctx.author.id,
             ctx.author.display_name, question, json.dumps(options), ends_at),
        )
        self.views.append(view)
        view.start_timer()


async def setup(bot):
    await bot.add_cog(Polls(bot))
