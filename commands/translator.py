import asyncio

import discord
from discord.ext import commands
from deep_translator import GoogleTranslator

MAX_CHARS = 4500  # Google's per-request limit is 5000

# Friendly extras on top of the full language list deep-translator provides
ALIASES = {
    "chinese": "zh-CN",
    "mandarin": "zh-CN",
    "cantonese": "zh-TW",
    "farsi": "fa",
    "tagalog": "tl",
    "burmese": "my",
    "portuguese-br": "pt",
}

# Used only if deep-translator can't give us its language list for some reason
FALLBACK_LANGUAGES = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "russian": "ru", "japanese": "ja", "korean": "ko",
    "chinese (simplified)": "zh-CN", "chinese (traditional)": "zh-TW", "hindi": "hi",
    "arabic": "ar", "turkish": "tr", "dutch": "nl", "polish": "pl", "urdu": "ur",
}


def load_languages() -> dict:
    """name -> code, e.g. {'english': 'en', 'hindi': 'hi', ...}"""
    try:
        langs = GoogleTranslator(source="auto", target="en").get_supported_languages(as_dict=True)
        if langs:
            return {name.lower(): code for name, code in langs.items()}
    except Exception as e:
        print(f"[Translator] Couldn't load language list, using fallback: {e}")
    return dict(FALLBACK_LANGUAGES)


class TranslatorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.languages = load_languages()                            # name -> code
        self.codes = {c.lower(): c for c in self.languages.values()}  # 'zh-cn' -> 'zh-CN'
        self.names = {c: n for n, c in self.languages.items()}        # code -> name

    def resolve_language(self, value: str):
        """Accepts a language name ('spanish') or code ('es'); returns the code or None."""
        value = value.lower().strip()
        if value in ALIASES:
            return ALIASES[value]
        if value in self.languages:
            return self.languages[value]
        if value in self.codes:
            return self.codes[value]
        return None

    @commands.command(
        name="translate",
        aliases=["tr"],
        usage="<language> <text>   (or reply to a message with: !translate <language>)",
        help="Translate text into any language.",
    )
    async def translate_text(self, ctx, target_lang: str, *, text: str = None):
        code = self.resolve_language(target_lang)
        if not code:
            return await ctx.reply(
                f"❌ I don't know the language `{target_lang}`.\n"
                f"Use a name or code, e.g. `!translate spanish Good morning` or `!translate hi How are you?`\n"
                f"See all options with `!languages`.",
                mention_author=False,
            )

        # No text given? Fall back to the message being replied to.
        if not text and ctx.message.reference:
            ref = ctx.message.reference.resolved
            if not isinstance(ref, discord.Message) and ctx.message.reference.message_id:
                try:
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                except discord.HTTPException:
                    ref = None
            if isinstance(ref, discord.Message):
                text = ref.content or (ref.embeds[0].description if ref.embeds else None)

        if not text:
            return await ctx.reply(
                "❗ Nothing to translate!\n"
                "Usage: `!translate <language> <text>` or reply to a message with `!translate <language>`.",
                mention_author=False,
            )
        if len(text) > MAX_CHARS:
            return await ctx.reply(f"❌ That's too long — please keep it under {MAX_CHARS} characters.", mention_author=False)

        async with ctx.typing():
            try:
                # deep-translator is synchronous, so run it off the event loop
                result = await asyncio.to_thread(
                    GoogleTranslator(source="auto", target=code).translate, text
                )
            except Exception as e:
                print(f"[Translator] {type(e).__name__}: {e}")
                return await ctx.reply(
                    "⚠️ The translation service didn't answer. Try again in a moment.",
                    mention_author=False,
                )

        if not result:
            return await ctx.reply("⚠️ I couldn't translate that. Is it just emojis or symbols?", mention_author=False)

        lang_name = self.names.get(code, code).title()
        embed = discord.Embed(
            title=f"🌐 Translated → {lang_name} ({code})",
            description=result[:4000],
            color=discord.Color.blurple(),
        )
        original = text if len(text) <= 900 else text[:897] + "..."
        embed.add_field(name="Original", value=original, inline=False)
        embed.set_footer(text=f"Requested by {ctx.author.display_name}")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="languages", aliases=["langs"], help="List the languages !translate understands.")
    async def languages_cmd(self, ctx):
        listing = ", ".join(f"{name.title()} (`{code}`)" for name, code in sorted(self.languages.items()))
        embed = discord.Embed(
            title="🌍 Supported languages",
            description=listing[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Use the name or the code: !translate french Hello  /  !translate fr Hello")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TranslatorCog(bot))
