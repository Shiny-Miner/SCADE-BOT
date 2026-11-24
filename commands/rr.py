import json
import os

import discord
from discord.ext import commands

# Only used ONCE to import the old mappings into the database.
LEGACY_JSON = os.path.join(os.path.dirname(__file__), "reaction_roles.json")


def normalize_emoji(emoji) -> str:
    """Unicode emoji -> itself, custom emoji -> '<:name:id>' / '<a:name:id>'."""
    return str(emoji)


def strip_variation(e: str) -> str:
    return e.replace("\ufe0f", "")  # invisible selector: "⚡" vs "⚡️"


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data = {}  # message_id(int) -> {emoji(str): role_id(int)}
        self.channels = {}  # message_id(int) -> channel_id(int) (when known)

    # ------------------------------------------------------------- loading
    async def cog_load(self):
        await self._import_legacy_json()
        await self._load_from_db()

    async def _import_legacy_json(self):
        db = self.bot.db
        if await db.meta_get("imported_rr_json"):
            return
        if os.path.exists(LEGACY_JSON):
            try:
                with open(LEGACY_JSON, "r", encoding="utf-8") as f:
                    raw = json.load(f)

                def work(conn):
                    for message_id, emoji_map in raw.items():
                        for emoji, role_id in emoji_map.items():
                            conn.execute(
                                "INSERT OR IGNORE INTO reaction_roles (message_id, emoji, role_id) VALUES (?, ?, ?)",
                                (int(message_id), emoji, int(role_id)),
                            )

                await db.transaction(work)
            except Exception as e:  # noqa: BLE001
                print(f"[ReactionRoles] Couldn't import {LEGACY_JSON}: {type(e).__name__}: {e}")
                return
        await db.meta_set("imported_rr_json", "1")

    async def _load_from_db(self):
        rows = await self.bot.db.fetchall("SELECT * FROM reaction_roles")
        self.data, self.channels = {}, {}
        for r in rows:
            self.data.setdefault(r["message_id"], {})[r["emoji"]] = r["role_id"]
            if r["channel_id"]:
                self.channels[r["message_id"]] = r["channel_id"]
        print(f"[ReactionRoles] Loaded {len(self.data)} reaction role message(s) from the database.")

    async def load_reaction_roles(self):
        """Called once when the bot is ready: make sure the bot's own reactions are on the messages."""
        for message_id, emoji_map in list(self.data.items()):
            message = await self._find_message(message_id)
            if message is None:
                continue
            for emoji in emoji_map:
                try:
                    already = any(str(r.emoji) == emoji and r.me for r in message.reactions)
                    if not already:
                        await message.add_reaction(discord.PartialEmoji.from_str(emoji))
                        print(f"🔁 Re-added emoji '{emoji}' to message {message_id}")
                except discord.HTTPException as e:
                    print(f"[ReactionRoles] Could not re-add '{emoji}' to {message_id}: {e}")

    async def _find_message(self, message_id, guild=None):
        """Find a message by ID. Remembers the channel in the database for next time."""
        known = self.channels.get(message_id)
        if known:
            channel = self.bot.get_channel(known)
            if channel:
                try:
                    return await channel.fetch_message(message_id)
                except discord.HTTPException:
                    pass
        guilds = [guild] if guild else self.bot.guilds
        for g in guilds:
            for channel in g.text_channels:
                if not channel.permissions_for(g.me).read_message_history:
                    continue
                try:
                    message = await channel.fetch_message(message_id)
                except discord.HTTPException:
                    continue
                self.channels[message_id] = channel.id
                await self.bot.db.execute(
                    "UPDATE reaction_roles SET channel_id = ?, guild_id = ? WHERE message_id = ?",
                    (channel.id, g.id, message_id),
                )
                return message
        return None

    # ------------------------------------------------------------ commands
    @commands.command(name="rr_add")
    @commands.has_permissions(manage_roles=True)
    async def rr_add(self, ctx, message_id: int, emoji: str, role: discord.Role):
        try:
            partial = await commands.PartialEmojiConverter().convert(ctx, emoji)
            emoji_key = normalize_emoji(partial)
            emoji_to_react = partial
        except commands.PartialEmojiConversionFailure:
            emoji_key = emoji
            emoji_to_react = emoji

        message = await self._find_message(message_id, ctx.guild)
        channel_id = message.channel.id if message else None

        await self.bot.db.execute(
            "INSERT INTO reaction_roles (message_id, emoji, role_id, guild_id, channel_id) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id, emoji) DO UPDATE SET role_id = excluded.role_id, "
            "guild_id = excluded.guild_id, channel_id = COALESCE(excluded.channel_id, reaction_roles.channel_id)",
            (message_id, emoji_key, role.id, ctx.guild.id, channel_id),
        )
        self.data.setdefault(message_id, {})[emoji_key] = role.id
        if channel_id:
            self.channels[message_id] = channel_id
        self.bot.dispatch("scade_data_changed")

        if message:
            try:
                await message.add_reaction(emoji_to_react)
            except discord.HTTPException as e:
                await ctx.send("⚠️ Couldn't add emoji to the message, but mapping was saved.")
                print(f"[rr_add] Error adding emoji: {e}")
        else:
            await ctx.send("⚠️ Couldn't find the message to add the emoji, but mapping was saved.")

        await ctx.send(f"✅ Linked emoji `{emoji_key}` to role `{role.name}` on message `{message_id}`.")

    @commands.command(name="rr_remove")
    @commands.has_permissions(manage_roles=True)
    async def rr_remove(self, ctx, message_id: int, emoji: str):
        """Remove a linked reaction role from a message."""
        try:
            partial = await commands.PartialEmojiConverter().convert(ctx, emoji)
            emoji_key = normalize_emoji(partial)
            emoji_to_remove = partial
        except commands.PartialEmojiConversionFailure:
            emoji_key = emoji
            emoji_to_remove = emoji

        if message_id not in self.data:
            return await ctx.send("❌ No reaction roles found for that message.")
        if emoji_key not in self.data[message_id]:
            return await ctx.send("❌ That emoji is not linked to any role on that message.")

        del self.data[message_id][emoji_key]
        if not self.data[message_id]:
            del self.data[message_id]
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE message_id = ? AND emoji = ?", (message_id, emoji_key)
        )
        self.bot.dispatch("scade_data_changed")

        message = await self._find_message(message_id, ctx.guild)
        if message:
            try:
                await message.clear_reaction(emoji_to_remove)
            except discord.HTTPException as e:
                await ctx.send("⚠️ Couldn't remove emoji from the message, but mapping was removed.")
                print(f"[rr_remove] Error removing emoji: {e}")

        await ctx.send(f"✅ Removed reaction role link for `{emoji_key}` on message `{message_id}`.")

    # ---------------------------------------------------------- diagnostics
    def role_problem(self, guild, role):
        """Why can't the bot hand out this role? Returns a readable reason, or None if it's fine."""
        me = guild.me
        if role is None:
            return "that role doesn't exist any more (was it deleted? run `!rr_add` again with the new role)"
        if role.is_default():
            return "`@everyone` can't be given to people"
        if role.managed:
            return f"**{role.name}** is managed by a bot/integration and can't be assigned manually"
        if not me.guild_permissions.manage_roles:
            return "I'm missing the **Manage Roles** permission"
        if role >= me.top_role:
            return (
                f"**{role.name}** is not *below* my highest role (**{me.top_role.name}**). "
                "Go to Server Settings → Roles and drag my role **above** it. "
                "(The Administrator permission does NOT bypass role order.)"
            )
        return None

    async def _tell_channel(self, channel_id, text):
        """Reaction events have no 'reply', so post a short temporary note in the channel."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.send(text[:1900], delete_after=25)
        except discord.HTTPException:
            pass

    @commands.command(name="rr_list")
    @commands.has_permissions(manage_roles=True)
    async def rr_list(self, ctx):
        """List every reaction-role message and whether it can work."""
        if not self.data:
            return await ctx.send("No reaction roles are set up. Use `!rr_add <message_id> <emoji> @role`.")
        lines = []
        for message_id, emoji_map in self.data.items():
            lines.append(f"**Message `{message_id}`**")
            for emoji, role_id in emoji_map.items():
                role = ctx.guild.get_role(role_id)
                problem = self.role_problem(ctx.guild, role)
                status = "✅" if problem is None else "⚠️"
                target = role.mention if role else "`" + str(role_id) + "` (missing)"
                lines.append(f"{status} {emoji} → {target}")
        await ctx.send("\n".join(lines)[:1990])

    @commands.command(name="rr_check", usage="[message_id]")
    @commands.has_permissions(manage_roles=True)
    async def rr_check(self, ctx, message_id: int = None):
        """Explain exactly why reaction roles might not be working."""
        me = ctx.guild.me
        report = [
            f"**Bot top role:** {me.top_role.mention} (position {me.top_role.position})",
            f"**Manage Roles permission:** {'✅' if me.guild_permissions.manage_roles else '❌ missing'}",
            f"**Reaction roles stored:** {len(self.data)} message(s)",
        ]
        ids = [message_id] if message_id else list(self.data)
        if message_id and message_id not in self.data:
            report.append(f"❌ Message `{message_id}` has **no** reaction roles saved. Run `!rr_add {message_id} <emoji> @role`.")
        for mid in ids:
            if mid not in self.data:
                continue
            message = await self._find_message(mid, ctx.guild)
            report.append(f"\n**Message `{mid}`**: " + ("✅ found" if message else "❌ I can't find/read it (wrong server? missing channel access?)"))
            for emoji, role_id in self.data[mid].items():
                role = ctx.guild.get_role(role_id)
                problem = self.role_problem(ctx.guild, role)
                report.append(f"{'✅' if problem is None else '❌'} {emoji} → {role.mention if role else role_id}" + (f"\n   ↳ {problem}" if problem else ""))
        await ctx.send("\n".join(report)[:1990], allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------ listeners
    def _match(self, message_id, emoji):
        """Return (emoji_key, role_id) if this reaction is linked to a role, else None."""
        emoji_map = self.data.get(message_id)
        if not emoji_map:
            return None
        if emoji in emoji_map:
            return emoji, emoji_map[emoji]
        wanted = strip_variation(emoji)
        for key, role_id in emoji_map.items():
            if strip_variation(key) == wanted:
                return key, role_id
        return None

    async def _get_member(self, guild, user_id, payload_member=None):
        member = payload_member or guild.get_member(user_id)
        if member:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.HTTPException:
            return None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return
        if payload.message_id not in self.data:
            return  # not a reaction-role message
        match = self._match(payload.message_id, normalize_emoji(payload.emoji))
        if not match:
            print(
                f"[ReactionRoles] Reaction {str(payload.emoji)!r} on message {payload.message_id} doesn't match "
                f"any saved emoji: {list(self.data[payload.message_id])}"
            )
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = await self._get_member(guild, payload.user_id, payload.member)
        if not member or member.bot:
            return

        role = guild.get_role(match[1])
        problem = self.role_problem(guild, role)
        if problem:
            print(f"❌ [ReactionRoles] Can't give role {match[1]} to {member}: {problem}")
            await self._tell_channel(payload.channel_id, f"⚠️ {member.mention}, I couldn't give you that role: {problem}")
            return
        try:
            await member.add_roles(role, reason="Reaction role")
            print(f"✅ Gave role '{role.name}' to {member.name}")
        except discord.HTTPException as e:
            print(f"❌ [ReactionRoles] Discord refused to give '{role.name}' to {member}: {e}")
            await self._tell_channel(payload.channel_id, f"⚠️ I couldn't give you **{role.name}**: Discord said `{e}`")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.message_id not in self.data:
            return
        match = self._match(payload.message_id, normalize_emoji(payload.emoji))
        if not match:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = await self._get_member(guild, payload.user_id)
        if not member:
            return

        role = guild.get_role(match[1])
        problem = self.role_problem(guild, role)
        if problem:
            print(f"❌ [ReactionRoles] Can't remove role {match[1]} from {member}: {problem}")
            return
        try:
            await member.remove_roles(role, reason="Reaction role removed")
            print(f"🔁 Removed role '{role.name}' from {member.name}")
        except discord.HTTPException as e:
            print(f"❌ [ReactionRoles] Discord refused to remove '{role.name}' from {member}: {e}")


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
