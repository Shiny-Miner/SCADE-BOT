import discord
from discord.ext import commands, tasks
from collections import defaultdict
import time

# Configurable constants
SPAM_MESSAGE_LIMIT = 5
SPAM_ATTACHMENT_LIMIT = 3
SPAM_CHANNEL_THRESHOLD = 5
TIME_WINDOW = 10
HACK_WINDOW = 30
TIMEOUT_DURATION = 300  # seconds

class AntiAbuseProtector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.msg_logs = defaultdict(list)  # user_id -> [timestamps]
        self.attach_logs = defaultdict(list)  # user_id -> [timestamps]
        self.repeated_logs = defaultdict(list)  # user_id -> [(msg, channel_id, timestamp)]
        self.cleanup_loop.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        now = time.time()

        # Track messages
        self.msg_logs[user_id].append(now)
        self.msg_logs[user_id] = [t for t in self.msg_logs[user_id] if now - t < TIME_WINDOW]

        if len(self.msg_logs[user_id]) > SPAM_MESSAGE_LIMIT:
            await self.timeout_user(message.author, message.guild, reason="sending too many messages")
            return

        # Track attachments
        self.attach_logs[user_id].extend([now] * len(message.attachments))
        self.attach_logs[user_id] = [t for t in self.attach_logs[user_id] if now - t < TIME_WINDOW]

        if len(self.attach_logs[user_id]) > SPAM_ATTACHMENT_LIMIT:
            await self.timeout_user(message.author, message.guild, reason="sending too many attachments")
            return

        # Detect repeated messages across channels
        content = message.content.strip().lower()
        if content:
            self.repeated_logs[user_id].append((content, message.channel.id, now))
            self.repeated_logs[user_id] = [
                (msg, ch, ts) for msg, ch, ts in self.repeated_logs[user_id] if now - ts < HACK_WINDOW
            ]

            # Count how many channels the same message was sent to
            msg_channels = defaultdict(set)
            for msg, ch, ts in self.repeated_logs[user_id]:
                msg_channels[msg].add(ch)

            for msg_text, ch_set in msg_channels.items():
                if len(ch_set) >= SPAM_CHANNEL_THRESHOLD:
                    await self.timeout_user(message.author, message.guild,
                        reason="spamming same message in many channels")
                    return

    async def timeout_user(self, member: discord.Member, guild: discord.Guild, reason: str):
        try:
            await member.timeout(discord.utils.utcnow() + discord.timedelta(seconds=TIMEOUT_DURATION), reason=reason)
        except discord.Forbidden:
            pass

        log_channel = discord.utils.get(guild.text_channels, name="modlog")
        if log_channel:
            await log_channel.send(
                f"⚠️ {member.mention} was timed out for: **{reason}**"
            )

    @tasks.loop(seconds=60)
    async def cleanup_loop(self):
        try:
            now = time.time()
            for logs in (self.msg_logs, self.attach_logs, self.repeated_logs):
                for user_id in list(logs.keys()):
                    if isinstance(logs[user_id], list):
                        logs[user_id] = [t for t in logs[user_id] if now - t < TIME_WINDOW]
                        if not logs[user_id]:
                            del logs[user_id]
                    else:
                        logs[user_id] = [
                            (msg, ch, ts)
                            for msg, ch, ts in logs[user_id]
                            if now - ts < HACK_WINDOW
                        ]
                        if not logs[user_id]:
                            del logs[user_id]
        except Exception as e:
            print(f"[cleanup_loop ERROR] {type(e).__name__}: {e}")

async def setup(bot):
    await bot.add_cog(AntiAbuseProtector(bot))
