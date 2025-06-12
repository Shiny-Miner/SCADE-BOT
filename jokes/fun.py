from discord.ext import commands
import discord
import random
import aiohttp
import os

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

headers = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}

async def generate_witty_reply(messages):
    async with aiohttp.ClientSession() as session:
        try:
            payload = {
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 1.3,
                "max_tokens": 300
            }

            async with session.post(GROQ_API_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    print(f"GROQ Error {response.status}: {text}")
                    return "Sorry, I forgot my punchline. 🪐"

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
        self.chat_histories = {}  # Store per-channel histories

    @commands.command(name="chat")
    async def chat_command(self, ctx, *, message: str = None):
        """Chat with the AI using !chat [message]"""
        if not message:
            await ctx.send("Say something after `!chat`!")
            return

        history = self.chat_histories.setdefault(ctx.channel.id, [])
        history.append({"role": "user", "content": message})

        messages = [{"role": "system", "content": "You're a funny and humorous AI chatbot and want to turn everything into funny conversation many times adding jokes or memes"}] + history

        try:
            reply = await generate_witty_reply(messages)
            history.append({"role": "assistant", "content": reply})
            await ctx.send(reply)
        except Exception as e:
            print(f"GROQ API error: {e}")
            await ctx.send("Oops! I tripped over a wire trying to think of something witty. 🧠")

    @commands.command(name="resetchat")
    async def reset_chat(self, ctx):
        self.chat_histories.pop(ctx.channel.id, None)
        await ctx.send("Chat history has been reset. Let's start fresh!")


async def setup(bot):
    await bot.add_cog(Fun(bot))
