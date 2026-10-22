# Tha code mining hub bot
SCADE bot code (Copyright to me)
This bot is a multi use bot developed single handedly by Shiny Miner.
Being used in Tha Code Mining Hub Discord Server.
Functionalities:
- Reaction roles
- Purge
- Lock/unlock
- Afk setting
- Anti abuse
- Emoji uploader and deleter
- Polls (timed, live vote bars, change-your-vote)
- Recall messages
- Translator (powered by deep-translator, supports replying to a message)
- Show off sunday event
- Welcomer
- AI chat (SCADE the stand-up comedian) + `!joke`
- Interactive `!help` menu with usage and examples for every command
- Guessing pokemon game (by image)

## Setup
Environment variables:
- `DISCORD_TOKEN` (required)
- `GROQ_API_KEY` (required for `!chat` and `!joke`)
- `GROQ_MODEL` (optional, override the default model if Groq retires it)

Install with `pip install -r requirements.txt`.

## Quick usage
- `!help` or `!help poll`
- `!poll 2m Best editor? | VS Code | Vim | Notepad`
- `!translate spanish Good morning` (or reply to a message with `!translate french`)
- `!chat tell me about recursion`

No one should use this code without permission, i could have made it private but my hosting site uses this so i can't do anything.

Made using Python 3.10.12 with discord.py
