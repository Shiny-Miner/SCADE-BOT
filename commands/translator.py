from discord.ext import commands
from googletrans import Translator, LANGUAGES

translator = Translator()

class TranslatorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="translate", help="Translate text. Usage: !translate <target_lang> <text>")
    async def translate_text(self, ctx, target_lang: str, *, text: str):
        target_lang = target_lang.lower()

        # Try converting full language name to code
        if target_lang not in LANGUAGES and target_lang in LANGUAGES.values():
            target_lang = [code for code, name in LANGUAGES.items() if name == target_lang][0]

        if target_lang not in LANGUAGES:
            await ctx.reply("❌ Invalid target language. Example: `!translate english hola`")
            return

        try:
            result = await translator.translate(text, dest=target_lang)
            await ctx.reply(f"**Translated ({result.src} → {result.dest}):** {result.text}")
        except Exception as e:
            await ctx.reply(f"⚠️ Translation failed: {e}")

async def setup(bot):
    await bot.add_cog(TranslatorCog(bot))
