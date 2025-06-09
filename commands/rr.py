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

class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        raw_data = load_data()
        self.data = {}  # Final structure: message_id -> emoji -> role_id

        @bot.event
        async def on_ready():
            guilds = self.bot.guilds
            for message_id, emoji_map in raw_data.items():
                self.data[message_id] = {}
                for emoji, role_name in emoji_map.items():
                    for guild in guilds:
                        role = discord.utils.get(guild.roles, name=role_name)
                        if role:
                            self.data[message_id][emoji] = role.id

    @commands.command(name="rr_add")
    @commands.has_permissions(manage_roles=True)
    async def rr_add(self, ctx, message_id: int, emoji: str, role: discord.Role):
        """Link a reaction emoji to a role on a specific message."""
        msg_id = str(message_id)
        if msg_id not in self.data:
            self.data[msg_id] = {}
        self.data[msg_id][emoji] = role.id
        save_data(self.data)

        # Try to add the emoji to the message
        try:
            channel = ctx.channel
            message = await channel.fetch_message(message_id)
            await message.add_reaction(emoji)
        except Exception:
            await ctx.send("⚠️ Couldn't add emoji to the message, but mapping was saved.")

        await ctx.send(f"✅ Linked emoji `{emoji}` to role `{role.name}` on message `{message_id}`.")

    @commands.command(name="rr_remove")
    @commands.has_permissions(manage_roles=True)
    async def rr_remove(self, ctx, message_id: int, emoji: str):
        """Remove a linked reaction role from a message."""
        msg_id = str(message_id)
        if msg_id not in self.data:
            return await ctx.send("❌ No reaction roles found for that message.")

        if emoji not in self.data[msg_id]:
            return await ctx.send("❌ That emoji is not linked to any role on that message.")

        del self.data[msg_id][emoji]
        if not self.data[msg_id]:
            del self.data[msg_id]  # Clean up empty

        save_data(self.data)

        # Try to remove the reaction from the message
        try:
            channel = ctx.channel
            message = await channel.fetch_message(message_id)
            await message.clear_reaction(emoji)
        except Exception:
            await ctx.send("⚠️ Couldn't remove emoji from the message, but mapping was removed.")

        await ctx.send(f"✅ Removed reaction role link for `{emoji}` on message `{message_id}`.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.message_id) not in self.data:
            return

        emoji = str(payload.emoji)
        role_id = self.data[str(payload.message_id)].get(emoji)
        if not role_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if member:
            role = guild.get_role(role_id)
            if role:
                await member.add_roles(role, reason="Reaction role")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if str(payload.message_id) not in self.data:
            return

        emoji = str(payload.emoji)
        role_id = self.data[str(payload.message_id)].get(emoji)
        if not role_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if member:
            role = guild.get_role(role_id)
            if role:
                await member.remove_roles(role, reason="Reaction role removed")

async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
