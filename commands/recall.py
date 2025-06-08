import discord
from discord.ext import commands
import json
import os

RECALL_FILE = "recall_messages.json"

# Make sure the JSON file exists
if not os.path.exists(RECALL_FILE):
    raise FileNotFoundError(f"❌ '{RECALL_FILE}' not found. Please create it manually with initial content.")

class Recall(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open(RECALL_FILE, 'r') as f:
            self.recall_messages = json.load(f)

    @commands.command(name="recall")
    async def recall(self, ctx, key: str = None):
        if not key:
            await ctx.send("❌ Please provide a key. Usage: `!recall <key>`")
            return
        key = key.lower()
        message = self.recall_messages.get(key)
        if message:
            await ctx.send(message)
        else:
            await ctx.send(f"❌ No message found for key: `{key}`")

    @commands.command(name="setrecall")
    @commands.has_permissions(administrator=True)
    async def setrecall(self, ctx, key: str, *, message: str):
        key = key.lower()
        self.recall_messages[key] = message
        with open(RECALL_FILE, 'w') as f:
            json.dump(self.recall_messages, f, indent=4)
        await ctx.send(f"✅ Set recall message for `{key}`.")

    @commands.command(name="delrecall")
    @commands.has_permissions(administrator=True)
    async def delrecall(self, ctx, key: str):
        if key in self.recall_messages:
            del self.recall_messages[key]
            with open(RECALL_FILE, 'w') as f:
                json.dump(self.recall_messages, f, indent=4)
            await ctx.send(f"🗑️ Deleted recall message for `{key}`.")
        else:
            await ctx.send(f"❌ No recall message found for `{key}`.")

    @commands.command(name="listrecall")
    async def listrecall(self, ctx):
        if not self.recall_messages:
            await ctx.send("No recall messages have been set.")
        else:
            keys = ', '.join(self.recall_messages.keys())
            await ctx.send(f"📚 Available keys: `{keys}`")

async def setup(bot):
    await bot.add_cog(Recall(bot))
