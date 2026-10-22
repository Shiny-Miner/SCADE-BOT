import difflib

import discord
from discord.ext import commands

# Pretty category -> the cogs that belong in it
CATEGORIES = {
    "🤖 Fun & AI": ["Fun"],
    "🧰 Utility": ["HelpCog", "Polls", "TranslatorCog", "Avatar", "AFK", "Recall"],
    "🎮 Games": ["GuessPokemon"],
    "🛡️ Moderation": ["Moderation", "ChannelLocker"],
    "⚙️ Server Tools": ["ReactionRoles", "EmojiManager", "Welcomer", "InvisibleSpy"],
}

# Description / example / notes for every command (keyed by full command name).
# Anything not listed here falls back to its docstring and auto-generated usage.
INFO = {
    "chat": {
        "desc": "Chat with SCADE, an AI that turns everything into a joke.",
        "example": "!chat explain recursion",
        "notes": "Remembers the last few messages in the channel. Use `!resetchat` to wipe its memory.",
    },
    "resetchat": {"desc": "Make SCADE forget this channel's chat history.", "example": "!resetchat"},
    "joke": {"desc": "Get a fresh joke, optionally about a topic.", "example": "!joke pokemon"},
    "translate": {
        "desc": "Translate text into any language (Google Translate).",
        "example": "!translate spanish Good morning everyone",
        "notes": "Use a language name or code (`es`, `hi`, `ja`…). You can also **reply to a message** with `!translate french` to translate it. Alias: `!tr`. See `!languages`.",
    },
    "languages": {"desc": "List every language `!translate` understands.", "example": "!languages"},
    "poll": {
        "desc": "Start a timed poll with live vote bars.",
        "example": "!poll 2m Best editor? | VS Code | Vim | Notepad",
        "notes": (
            "Time is optional: `30`, `90s`, `5m`, `2h` (10s–24h, default 60s).\n"
            "Separate the question and options with `|`, or use quotes: `!poll 30 \"Tabs or spaces?\" \"Tabs\" \"Spaces\"`.\n"
            "2–10 options. Leave the options off for a quick 👍/👎 poll. People can change their vote."
        ),
    },
    "afk": {"desc": "Set yourself AFK. People who ping you will see your reason.", "example": "!afk gone to eat"},
    "av": {"desc": "Show your avatar, or someone else's.", "example": "!av @someone"},
    "recall": {"desc": "Show a saved message by its key.", "example": "!recall rules"},
    "setrecall": {"desc": "Save a message under a key. (Admin)", "example": "!setrecall rules Be nice!"},
    "delrecall": {"desc": "Delete a saved recall message. (Admin)", "example": "!delrecall rules"},
    "listrecall": {"desc": "List all saved recall keys.", "example": "!listrecall"},
    "guesspoke": {"desc": "Start a guess-the-Pokémon game right now.", "example": "!guesspoke",
                  "notes": "One also pops up on its own after lots of chatting. Type the name to guess!"},
    "hint": {"desc": "Get a hint during an active Pokémon game.", "example": "!hint"},
    "lock": {"desc": "Lock this channel so @everyone can't send messages.", "example": "!lock"},
    "unlock": {"desc": "Unlock this channel again.", "example": "!unlock"},
    "purge": {"desc": "Bulk-delete recent messages in this channel.", "example": "!purge 20"},
    "ban": {"desc": "Ban a member.", "example": "!ban @user spamming"},
    "kick": {"desc": "Kick a member.", "example": "!kick @user breaking rules"},
    "softban": {"desc": "Ban + unban to wipe a member's recent messages.", "example": "!softban @user raid spam"},
    "mute": {"desc": "Give a member the Muted role.", "example": "!mute @user cool off"},
    "unmute": {"desc": "Remove the Muted role.", "example": "!unmute @user"},
    "warn": {"desc": "Warn a member.", "example": "!warn @user please read the rules"},
    "warnings": {"desc": "Show a member's warnings.", "example": "!warnings @user"},
    "rr_add": {
        "desc": "Link an emoji to a role on a message (reaction roles).",
        "example": "!rr_add 123456789012345678 ⚡ @Role",
        "notes": "Get the message ID by enabling Developer Mode → right-click the message → Copy Message ID.",
    },
    "rr_remove": {"desc": "Remove a reaction-role link from a message.", "example": "!rr_remove 123456789012345678 ⚡"},
    "emoji": {"desc": "Add or remove custom emojis.", "example": "!emoji add 123456789012345678"},
    "emoji add": {"desc": "Copy a custom emoji into this server by its ID.", "example": "!emoji add 123456789012345678"},
    "emoji remove": {"desc": "Delete a custom emoji from this server by its ID.", "example": "!emoji remove 123456789012345678"},
    "test_welcome": {"desc": "Preview the welcome message.", "example": "!test_welcome"},
    "test_leave": {"desc": "Preview the farewell message.", "example": "!test_leave"},
    "invisible_users": {"desc": "List members who appear invisible. (Owner)", "example": "!invisible_users"},
    "help": {"desc": "Show this menu, or details for one command.", "example": "!help poll"},
}


def usage_line(ctx, cmd: commands.Command) -> str:
    sig = cmd.usage if cmd.usage is not None else cmd.signature
    return f"{ctx.clean_prefix}{cmd.qualified_name} {sig}".strip()


def describe(cmd: commands.Command) -> str:
    info = INFO.get(cmd.qualified_name, {})
    if info.get("desc"):
        return info["desc"]
    return cmd.help.strip().splitlines()[0] if cmd.help else "No description yet."


async def can_see(ctx, cmd: commands.Command) -> bool:
    if cmd.hidden:
        return False
    try:
        return await cmd.can_run(ctx)
    except Exception:
        return False


class HelpSelect(discord.ui.Select):
    def __init__(self, pages: dict):
        self.pages = pages
        options = [discord.SelectOption(label="Home", emoji="🏠", value="home", description="Overview of all categories")]
        for name in pages:
            if name == "home":
                continue
            emoji, _, label = name.partition(" ")
            options.append(discord.SelectOption(label=label, emoji=emoji, value=name))
        super().__init__(placeholder="Pick a category…", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.pages[self.values[0]])


class HelpView(discord.ui.View):
    def __init__(self, author_id: int, pages: dict):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.message = None
        self.add_item(HelpSelect(pages))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Type `!help` yourself to get your own menu 😉", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def collect(self, ctx):
        """category name -> list of commands this user can actually run."""
        grouped = {}
        placed = set()
        for category, cog_names in CATEGORIES.items():
            for cog_name in cog_names:
                cog = self.bot.get_cog(cog_name)
                if not cog:
                    continue
                placed.add(cog_name)
                for cmd in cog.walk_commands():
                    if await can_see(ctx, cmd):
                        grouped.setdefault(category, []).append(cmd)
        # Any cog we forgot to categorise still shows up
        for cog_name, cog in self.bot.cogs.items():
            if cog_name in placed:
                continue
            for cmd in cog.walk_commands():
                if await can_see(ctx, cmd):
                    grouped.setdefault("📦 Other", []).append(cmd)
        return grouped

    @commands.command(name="help", usage="[command]", help="Show this menu, or details for one command.")
    async def help_command(self, ctx, *, command: str = None):
        if command:
            return await self.send_command_help(ctx, command)

        grouped = await self.collect(ctx)

        home = discord.Embed(
            title="⛏️ SCADE Bot: Help",
            description=(
                f"Pick a category from the dropdown to see **how to use every command**.\n"
                f"Or get details on one command: `{ctx.clean_prefix}help <command>` (e.g. `{ctx.clean_prefix}help poll`)."
            ),
            color=discord.Color.blurple(),
        )
        pages = {"home": home}

        for category, cmds in grouped.items():
            names = " ".join(f"`{c.qualified_name}`" for c in cmds)
            home.add_field(name=category, value=names, inline=False)

            lines = []
            for c in cmds:
                info = INFO.get(c.qualified_name, {})
                block = f"**`{usage_line(ctx, c)}`**\n{describe(c)}"
                if info.get("example"):
                    block += f"\n*Example:* `{info['example']}`"
                lines.append(block)
            embed = discord.Embed(title=category, description="\n\n".join(lines)[:4000], color=discord.Color.blurple())
            embed.set_footer(text=f"{ctx.clean_prefix}help <command> for more details")
            pages[category] = embed

        home.set_footer(text="Only commands you're allowed to use are shown.")
        view = HelpView(ctx.author.id, pages)
        view.message = await ctx.send(embed=home, view=view)

    async def send_command_help(self, ctx, query: str):
        query = query.strip().removeprefix(ctx.clean_prefix).strip().lower()
        cmd = self.bot.get_command(query)
        if cmd is None or cmd.hidden:
            all_names = [c.qualified_name for c in self.bot.walk_commands() if not c.hidden]
            close = difflib.get_close_matches(query, all_names, n=3, cutoff=0.5)
            hint = f" Did you mean {', '.join(f'`{n}`' for n in close)}?" if close else ""
            return await ctx.send(f"❌ I don't have a command called `{query}`.{hint}")

        info = INFO.get(cmd.qualified_name, {})
        embed = discord.Embed(title=f"{ctx.clean_prefix}{cmd.qualified_name}", description=describe(cmd), color=discord.Color.blurple())
        embed.add_field(name="Usage", value=f"`{usage_line(ctx, cmd)}`", inline=False)
        if info.get("example"):
            embed.add_field(name="Example", value=f"`{info['example']}`", inline=False)
        if cmd.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{ctx.clean_prefix}{a}`" for a in cmd.aliases), inline=False)
        if info.get("notes"):
            embed.add_field(name="Good to know", value=info["notes"][:1024], inline=False)
        if isinstance(cmd, commands.Group):
            subs = ", ".join(f"`{s.name}`" for s in cmd.commands)
            embed.add_field(name="Subcommands", value=subs, inline=False)
        embed.set_footer(text="<required>  [optional]  — don't type the brackets")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
