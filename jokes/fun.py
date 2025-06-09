from discord.ext import commands
import discord
import random
import aiohttp

GROQ_API_KEY = "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"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

headers = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

async def generate_witty_reply(user_message):
    async with aiohttp.ClientSession() as session:
        try:
            payload = {
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": "You're a witty and humorous AI assistant."},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.8,
                "max_tokens": 100
            }

            async with session.post(GROQ_API_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    print(f"GROQ Error {response.status}: {text}")
                    return "Sorry, I forgot my punchline. 🤐"

                data = await response.json()
                return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            print(f"GROQ API error: {e}")
            return "Oops! I tripped over a wire again."


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.jokes = [
            "Why did the chicken join a band? Because it had the drumsticks!",
            "I told my computer I needed a break, and now it won't stop sending me vacation ads.",
            "Parallel lines have so much in common… it’s a shame they’ll never meet.",
            "Why do Java developers wear glasses? Because they don't see sharp.",
        ]

    @commands.command(name="chat")
    async def chat_command(self, ctx, *, message: str = None):
        """Chat with the AI using !chat [message]"""
        if not message:
            await ctx.send("Say something after `!chat`!")
            return
        try:
            reply = await generate_witty_reply(message)
            await ctx.send(reply)
        except Exception as e:
            print(f"GROQ API error: {e}")
            await ctx.send("Oops! I tripped over a wire trying to think of something witty. 🤖")

async def setup(bot):
    await bot.add_cog(Fun(bot))
