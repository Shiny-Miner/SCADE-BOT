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
- Pokétwo-style Pokémon game: wild pokémon spawn as people chat, `!catch` them, your selected pokémon earns XP from chatting and evolves (by level, friendship, stones and trading), pokédex, shiny hunting, trading, turn-based battles (`!battle`, `!team`, `!moves`), a coin market (`!market`), shop, leaderboards
- Everything is saved in one SQLite database (recalls, reaction roles, AFK, warnings, polls, the whole Pokémon game)

## Setup
Environment variables:
- `DISCORD_TOKEN` (required)
- `GROQ_API_KEY` (required for `!chat` and `!joke`)
- `GROQ_MODEL` (optional, leave it unset to use the default `openai/gpt-oss-120b`; the old `llama-3.3-70b-versatile` was shut down by Groq)
- `DB_PATH` (recommended) where the SQLite file lives, e.g. `/data/scade.db`. Point it at a **persistent disk/volume** of your host.
- `BACKUP_CHANNEL_ID` (recommended) ID of a **private** channel the bot can post files in. The bot uploads compressed database backups there and **automatically restores the newest one** if it starts with no database file.

### Real database (PostgreSQL), recommended
Set `DATABASE_URL` to a PostgreSQL connection string and the bot stores everything there instead of a local file, so redeploys and moving hosts never lose data. Free options: [Neon](https://neon.tech) or [Supabase](https://supabase.com). Copy the connection string they give you (it looks like `postgresql://user:password@host/dbname?sslmode=require`) into `.env` or your host's variables.
To move data you already have in SQLite: `python migrate_to_postgres.py` (safe to run twice). With PostgreSQL you don't need `DB_PATH` or `BACKUP_CHANNEL_ID`.
If `DATABASE_URL` is wrong the bot stops with a clear error instead of silently using another database.

### Keeping your data with the local SQLite file (no DATABASE_URL)
Many hosts reset the project folder on every deploy, which erases any file the bot wrote. SCADE protects you in two ways, use both if you can:
1. `DB_PATH` on a persistent disk, so the file is never wiped.
2. `BACKUP_CHANNEL_ID`, so even a wiped disk is restored from Discord on startup. Backups are made every 30 minutes (only if something changed), ~45 seconds after important edits (recalls, reaction roles, warnings), and on shutdown.

Owner commands: `!dbstatus` (where the DB is + what's inside + last backup), `!backup` (backup now + DM a copy), `!restore confirm` (attach a backup file).
The old `recall_messages.json` / `reaction_roles.json` are imported **once** into the database; after that the database is the source of truth.

Install with `pip install -r requirements.txt`.

## Quick usage
- `!help` or `!help poll`
- `!poll 2m Best editor? | VS Code | Vim | Notepad`
- `!translate spanish Good morning` (or reply to a message with `!translate french`)
- `!chat tell me about recursion`
- `!start` then `!pick bulbasaur` to begin the Pokémon game, `!catch <name>` when one appears

No one should use this code without permission, i could have made it private but my hosting site uses this so i can't do anything.

Made using Python 3.10.12 with discord.py
