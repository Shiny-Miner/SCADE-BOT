import discord
from discord.ext import commands
import json
import os

REACTION_ROLE_FILE = "reaction_roles.json"

def load_data():
    if os.path.exists(REACTION_ROLE_FILE):
        with open(REACTION_ROLE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(REACTION_ROLE_FILE, "w") as f:
        json.dump(data, f, indent=4)

def normalize_emoji(emoji):
    if hasattr(emoji, 'id') and emoji.id:  # custom emoji
        return f"<:{emoji.name}:{emoji.id}>"
    return str(emoji)

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data = {}  # message_id -> emoji -> role_id

    async def cog_load(self):
        print(f"[ReactionRoles] Loading data for messages...")
        raw_data = load_data()
        for message_id, emoji_map in raw_data.items():
            self.data[message_id] = {}
            for emoji, role_id in emoji_map.items():
                self.data[message_id][emoji] = role_id
        print(f"[ReactionRoles] Loaded {len(self.data)} reaction role messages.")

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

        msg_id = str(message_id)
        if msg_id not in self.data:
            self.data[msg_id] = {}
        self.data[msg_id][emoji_key] = role.id
        save_data(self.data)

        try:
            message = await ctx.channel.fetch_message(message_id)
            await message.add_reaction(emoji_to_react)
        except Exception as e:
            await ctx.send("⚠️ Couldn't add emoji to the message, but mapping was saved.")
            print(f"[rr_add] Error adding emoji: {e}")

        await ctx.send(f"✅ Linked emoji `{emoji_key}` to role `{role.name}` on message `{message_id}`.")

    @commands.command(name="rr_remove")
    @commands.has_permissions(manage_roles=True)
    async def rr_remove(self, ctx, message_id: int, emoji: str):
        msg_id = str(message_id)

        try:
            partial = await commands.PartialEmojiConverter().convert(ctx, emoji)
            emoji_key = normalize_emoji(partial)
            emoji_to_remove = partial
        except commands.PartialEmojiConversionFailure:
            emoji_key = emoji
            emoji_to_remove = emoji

        if msg_id not in self.data:
            return await ctx.send("❌ No reaction roles found for that message.")

        if emoji_key not in self.data[msg_id]:
            return await ctx.send("❌ That emoji is not linked to any role on that message.")

        del self.data[msg_id][emoji_key]
        if not self.data[msg_id]:
            del self.data[msg_id]

        save_data(self.data)

        try:
            message = await ctx.channel.fetch_message(message_id)
            await message.clear_reaction(emoji_to_remove)
        except Exception as e:
            await ctx.send("⚠️ Couldn't remove emoji from the message, but mapping was removed.")
            print(f"[rr_remove] Error removing emoji: {e}")

        await ctx.send(f"✅ Removed reaction role link for `{emoji_key}` on message `{message_id}`.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        msg_id = str(payload.message_id)
        emoji = normalize_emoji(payload.emoji)

        if msg_id not in self.data or emoji not in self.data[msg_id]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member:
            return

        role_id = self.data[msg_id][emoji]
        role = guild.get_role(role_id)
        if role and role < guild.me.top_role:
            try:
                await member.add_roles(role, reason="Reaction role")
                print(f"✅ Gave role '{role.name}' to {member.name}")
            except discord.Forbidden:
                print(f"❌ Missing permissions to assign role '{role.name}'.")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        msg_id = str(payload.message_id)
        emoji = normalize_emoji(payload.emoji)

        if msg_id not in self.data or emoji not in self.data[msg_id]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member:
            return

        role_id = self.data[msg_id][emoji]
        role = guild.get_role(role_id)
        if role and role < guild.me.top_role:
            try:
                await member.remove_roles(role, reason="Reaction role removed")
                print(f"🔁 Removed role '{role.name}' from {member.name}")
            except discord.Forbidden:
                print(f"❌ Missing permissions to remove role '{role.name}'.")

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
