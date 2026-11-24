"""
One-time helper: copy everything from your SQLite file into your PostgreSQL database.

  1. Set DATABASE_URL (in .env or your shell) to your PostgreSQL connection string.
  2. Run:   python migrate_to_postgres.py                (uses data/scade.db or DB_PATH)
            python migrate_to_postgres.py path/to/scade.db

Safe to run more than once: rows that already exist are skipped.
"""
import os
import sqlite3
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from database import DEFAULT_DB_PATH, PostgresDatabase, create_database  # noqa: E402

TABLES = [
    "recalls", "reaction_roles", "afk", "warnings", "polls", "poll_votes", "guild_settings",
    "species_names", "species_data", "players", "pokemon", "pokedex", "shiny_hunt", "items", "incense",
    "teams", "market",
]
SERIAL_TABLES = ["pokemon", "warnings", "market"]  # tables with an auto-numbered id


def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else (os.environ.get("DB_PATH") or DEFAULT_DB_PATH)
    if not os.path.exists(src_path):
        sys.exit(f"❌ SQLite file not found: {src_path}")
    if not os.environ.get("DATABASE_URL", "").strip():
        sys.exit("❌ DATABASE_URL is not set. Put your PostgreSQL connection string in .env first.")

    db = create_database(DEFAULT_DB_PATH)
    if not isinstance(db, PostgresDatabase):
        sys.exit("❌ DATABASE_URL did not select PostgreSQL.")
    print(f"Source : {src_path}\nTarget : {db.path}")
    db._connect()  # creates the tables if they don't exist yet

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row

    def copy_all(c):
        report = {}
        for table in TABLES:
            cols = [r["name"] for r in src.execute(f"PRAGMA table_info({table})")]
            if not cols:
                continue
            rows = [tuple(r) for r in src.execute(f"SELECT {', '.join(cols)} FROM {table}")]
            if rows:
                marks = ", ".join("?" * len(cols))
                c.executemany(f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({marks})", rows)
            report[table] = len(rows)
        # keep "already imported the old JSON files" flags so deleted recalls don't come back
        for key, value in [(r["key"], r["value"]) for r in src.execute("SELECT key, value FROM meta")]:
            if key.startswith("imported_") or key == "names_fetched_at":
                c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, value))
        for table in SERIAL_TABLES:  # make the next auto id come after the copied ones
            c.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))")
        return report

    report = db._run(copy_all)
    print("\nCopied rows:")
    for table, n in report.items():
        print(f"  {table:<15} {n}")
    print("\n✅ Done. Start the bot normally: it will now use PostgreSQL.")


if __name__ == "__main__":
    main()
