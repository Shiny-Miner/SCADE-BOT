import asyncio
import re
import shlex
from datetime import timedelta

import discord
from discord.ext import commands

DEFAULT_DURATION = 60          # seconds, when the user doesn't give a time
MIN_DURATION = 10              # seconds
MAX_DURATION = 24 * 60 * 60    # 24 hours
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
            f"Poll time must be between **{MIN_DURATION}s** and **24h** "
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
    def __init__(self, index: int, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
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
        # Update the poll message live, which also acknowledges the click
        await interaction.response.edit_message(embed=view.build_embed(), view=view)
        note = "changed your vote to" if previous is not None else "voted for"
        await interaction.followup.send(f"✅ You {note} **{self.label}**!", ephemeral=True)


class PollView(discord.ui.View):
    def __init__(self, author: discord.abc.User, question: str, options, duration: int):
        # timeout=None on purpose: discord.py resets a View's timeout after every
        # click, so a busy poll would never close. We run our own timer instead.
        super().__init__(timeout=None)
        self.author = author
        self.question = question
        self.options = options
        self.duration = duration
        self.votes = {}  # user_id -> option index
        self.closed = False
        self.message = None
        self.ends_at = discord.utils.utcnow() + timedelta(seconds=duration)
        self._timer = None

        for i, label in enumerate(options):
            self.add_item(PollButton(i, label))

    def counts(self):
        counts = [0] * len(self.options)
        for idx in self.votes.values():
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
            footer = f"Final result • {total} vote{'s' if total != 1 else ''} • Started by {self.author.display_name}"
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
            footer = f"Started by {self.author.display_name} • Click a button to vote — you can change your vote"
            lines.append(f"\n⏳ Closes <t:{int(self.ends_at.timestamp())}:R>")

        embed = discord.Embed(title=title, description=f"### {self.question}\n\n" + "\n\n".join(lines), color=color)
        embed.set_footer(text=footer)
        return embed

    def start_timer(self):
        self._timer = asyncio.create_task(self._close_later())

    async def _close_later(self):
        await asyncio.sleep(self.duration)
        await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        for child in self.children:
            child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(embed=self.build_embed(), view=self)
            except discord.HTTPException as e:
                print(f"[Poll] Couldn't edit finished poll: {e}")


class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
                value=f"Optional, e.g. `30`, `90s`, `5m`, `2h` (min {MIN_DURATION}s, max 24h, default {DEFAULT_DURATION}s).",
                inline=False,
            )
            return await ctx.send(embed=embed)

        view = PollView(ctx.author, question, options, duration)
        view.message = await ctx.send(embed=view.build_embed(), view=view)
        view.start_timer()


async def setup(bot):
    await bot.add_cog(Polls(bot))
