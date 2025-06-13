import discord
from discord.ext import commands
import re
from collections import Counter

MAX_MESSAGES = 2000  # Messages per channel to scan
STOP_WORDS = {"the", "and", "or", "is", "a", "an", "to", "in", "of", "on", "at", "for", "it", "as", "be", "with", "this", "that", "are", "was", "were", "has", "have", "you", "your", "i", "my"}

def tokenize(text):
    return [word.lower() for word in re.findall(r'\b\w+\b', text) if word.lower() not in STOP_WORDS]

class ChatSummaryFAQ(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def word_overlap_score(self, current_words, past_words):
        current_counter = Counter(current_words)
        past_counter = Counter(past_words)
        common = current_counter & past_counter
        return sum(common.values())

    async def search_all_channels(self, guild, current_question):
        best_score = 0
        best_match = None
        best_index = -1
        best_channel = None
        current_words = tokenize(current_question)

        ALLOWED_CHANNEL_IDS = []  # Optional: add your channel IDs to search, or leave empty to search all

        for channel in guild.text_channels:
            if ALLOWED_CHANNEL_IDS and channel.id not in ALLOWED_CHANNEL_IDS:
                continue

            try:
                history = []
                async for msg in channel.history(limit=MAX_MESSAGES):
                    if not msg.author.bot:
                        history.append(msg)
                await asyncio.sleep(0.7)  # ✅ delay to avoid rate-limiting

                for i, msg in enumerate(history):
                    score = self.word_overlap_score(current_words, tokenize(msg.content))
                    if score > best_score:
                        best_score = score
                        best_match = history
                        best_index = i
                        best_channel = channel

            except discord.Forbidden:
                print(f"[WARNING] No access to {channel.name}")
                continue
            except discord.HTTPException as e:
                print(f"[ERROR] Failed to fetch messages from {channel.name}: {e}")
                continue


        return best_match, best_index, best_score, best_channel

    def make_summary(self, messages, index):
        start = max(0, index - 5)
        end = min(len(messages), index + 5)
        context_msgs = messages[start:end]
        summary = []
        for msg in context_msgs:
            summary.append(f"**{msg.author.display_name}:** {msg.content[:200]}")
        return "\n".join(summary)

    MAX_DISCORD_MSG_LENGTH = 1900  # Leave room for header and footer

    async def handle_question(self, message, question_text):
        try:
            match, index, score, channel = await self.search_all_channels(message.guild, question_text)
            print(f"[DEBUG] Best score: {score}, Channel: {channel}, Index: {index}")

            if score >= 2 and match and channel:
                summary = self.make_summary(match, index)

                # Truncate if too long
                if len(summary) > MAX_DISCORD_MSG_LENGTH:
                    summary = summary[:MAX_DISCORD_MSG_LENGTH] + "\n... (truncated)"

                await message.reply(
                    f"🔁 Found a similar conversation in {channel.mention}:\n\n{summary}\n\n📍 [Jump]({match[index].jump_url})",
                    mention_author=False
                )
            else:
                await message.reply("❌ No similar messages found.", mention_author=False)
        except Exception as e:
            await message.reply(f"⚠️ Error during search: {e}")
            print(f"[ERROR] Exception in handle_question: {e}")


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild or not message.content.endswith("?"):
            return
        await self.handle_question(message, message.content)

    @commands.command(name="similar")
    async def similar_cmd(self, ctx, *, question: str):
        """Manually check if a similar question was asked before."""
        await self.handle_question(ctx.message, question)

async def setup(bot):
    await bot.add_cog(ChatSummaryFAQ(bot))
