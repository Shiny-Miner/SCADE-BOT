"""
SCADE bot: shared SQLite storage.

Everything that must survive a restart/redeploy (recalls, reaction roles, AFK,
warnings, polls, the whole Pokémon game...) lives in ONE SQLite file.

WHERE the file lives matters:
  * Set the DB_PATH environment variable to a folder that your host keeps between
    deploys (a "persistent volume" / "disk"). Example: DB_PATH=/data/scade.db
  * If your host has no persistent storage, set BACKUP_CHANNEL_ID instead. The bot
    then uploads compressed backups to that Discord channel and automatically
    restores the newest one when it starts with an empty/missing database.
  * Best: use both.
"""

import asyncio
import gzip
import os
import re
import sqlite3
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "scade.db")

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- !setrecall / !recall   (guild_id 0 = available in every server)
CREATE TABLE IF NOT EXISTS recalls (
    guild_id   INTEGER NOT NULL DEFAULT 0,
    key        TEXT    NOT NULL,
    message    TEXT    NOT NULL,
    created_by INTEGER,
    created_at INTEGER,
    PRIMARY KEY (guild_id, key)
);

-- reaction roles
CREATE TABLE IF NOT EXISTS reaction_roles (
    message_id INTEGER NOT NULL,
    emoji      TEXT    NOT NULL,
    role_id    INTEGER NOT NULL,
    guild_id   INTEGER NOT NULL DEFAULT 0,
    channel_id INTEGER,
    PRIMARY KEY (message_id, emoji)
);

-- !afk
CREATE TABLE IF NOT EXISTS afk (
    user_id INTEGER PRIMARY KEY,
    reason  TEXT,
    since   INTEGER
);

-- !warn
CREATE TABLE IF NOT EXISTS warnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    moderator_id INTEGER,
    reason       TEXT,
    created_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_warnings_user ON warnings (guild_id, user_id);

-- !poll (survives restarts, buttons keep working)
CREATE TABLE IF NOT EXISTS polls (
    token       TEXT PRIMARY KEY,
    message_id  INTEGER,
    channel_id  INTEGER,
    guild_id    INTEGER,
    author_id   INTEGER,
    author_name TEXT,
    question    TEXT,
    options     TEXT,
    ends_at     INTEGER,
    closed      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS poll_votes (
    token        TEXT    NOT NULL,
    user_id      INTEGER NOT NULL,
    option_index INTEGER NOT NULL,
    PRIMARY KEY (token, user_id)
);

-- per-server settings
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id       INTEGER PRIMARY KEY,
    spawn_channels TEXT NOT NULL DEFAULT '[]'
);

-- ===================== Pokémon game =====================
CREATE TABLE IF NOT EXISTS species_names (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS species_data (
    id         INTEGER PRIMARY KEY,
    data       TEXT NOT NULL,
    fetched_at INTEGER
);

CREATE TABLE IF NOT EXISTS players (
    user_id      INTEGER PRIMARY KEY,
    coins        INTEGER NOT NULL DEFAULT 0,
    selected     INTEGER,
    next_num     INTEGER NOT NULL DEFAULT 1,
    total_caught INTEGER NOT NULL DEFAULT 0,
    shiny_caught INTEGER NOT NULL DEFAULT 0,
    daily_last   INTEGER NOT NULL DEFAULT 0,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    silenced     INTEGER NOT NULL DEFAULT 0,
    started_at   INTEGER
);

CREATE TABLE IF NOT EXISTS pokemon (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id       INTEGER NOT NULL,
    num            INTEGER NOT NULL,
    species_id     INTEGER NOT NULL,
    nickname       TEXT,
    level          INTEGER NOT NULL DEFAULT 1,
    xp             INTEGER NOT NULL DEFAULT 0,
    shiny          INTEGER NOT NULL DEFAULT 0,
    nature         TEXT    NOT NULL,
    iv_hp          INTEGER NOT NULL,
    iv_atk         INTEGER NOT NULL,
    iv_def         INTEGER NOT NULL,
    iv_spa         INTEGER NOT NULL,
    iv_spd         INTEGER NOT NULL,
    iv_spe         INTEGER NOT NULL,
    favorite       INTEGER NOT NULL DEFAULT 0,
    caught_at      INTEGER,
    original_owner INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pokemon_owner ON pokemon (owner_id, num);
CREATE INDEX IF NOT EXISTS idx_pokemon_species ON pokemon (owner_id, species_id);

CREATE TABLE IF NOT EXISTS pokedex (
    user_id    INTEGER NOT NULL,
    species_id INTEGER NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    first_at   INTEGER,
    PRIMARY KEY (user_id, species_id)
);

CREATE TABLE IF NOT EXISTS shiny_hunt (
    user_id    INTEGER PRIMARY KEY,
    species_id INTEGER NOT NULL,
    streak     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS items (
    user_id INTEGER NOT NULL,
    item    TEXT    NOT NULL,
    qty     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item)
);

CREATE TABLE IF NOT EXISTS incense (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER,
    owner_id   INTEGER,
    expires_at INTEGER NOT NULL
);
"""

SCHEMA_V2 = """
-- battles, teams and the market
ALTER TABLE players ADD COLUMN battles_won   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN battles_lost  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN battle_day    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN battle_count  INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS teams (
    user_id    INTEGER NOT NULL,
    slot       INTEGER NOT NULL,
    pokemon_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, slot)
);

CREATE TABLE IF NOT EXISTS market (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id  INTEGER NOT NULL,
    pokemon_id INTEGER NOT NULL,
    price      INTEGER NOT NULL,
    listed_at  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_market_pokemon ON market (pokemon_id);
"""

# version -> script. Add SCHEMA_V3 etc. here later; never edit an old one.
MIGRATIONS = {1: SCHEMA_V1, 2: SCHEMA_V2}


class Database:
    """One SQLite connection shared by the whole bot (thread-safe, async-friendly)."""

    kind = "sqlite"

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.conn = None
        self.fresh = False  # True when the file did not exist before this start
        self._lock = threading.RLock()

    # ------------------------------------------------------------ connection
    async def connect(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fresh = not os.path.exists(self.path)
        await asyncio.to_thread(self._connect)

    def _connect(self):
        # isolation_level=None -> we control transactions ourselves
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self._migrate()

    def _migrate(self):
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for version in sorted(MIGRATIONS):
            if version > current:
                self.conn.executescript(MIGRATIONS[version])
                self.conn.execute(f"PRAGMA user_version = {version}")
                current = version
        self.conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('created_at', ?)", (str(int(time.time())),)
        )

    async def close(self):
        def _close():
            with self._lock:
                if self.conn is not None:
                    self.conn.close()
                    self.conn = None

        await asyncio.to_thread(_close)

    # --------------------------------------------------------------- queries
    def _run(self, fn):
        with self._lock:
            return fn(self.conn)

    async def run(self, fn):
        """Run fn(conn) in a worker thread (no transaction)."""
        return await asyncio.to_thread(self._run, fn)

    async def execute(self, sql, params=()):
        def work(conn):
            return conn.execute(sql, params).lastrowid

        return await self.run(work)

    async def fetchone(self, sql, params=()):
        return await self.run(lambda conn: conn.execute(sql, params).fetchone())

    async def fetchall(self, sql, params=()):
        return await self.run(lambda conn: conn.execute(sql, params).fetchall())

    async def transaction(self, fn):
        """
        Run fn(conn) atomically: everything inside commits together or not at all.
        fn is a normal (sync) function; keep it short and do not await inside it.
        """

        def work(conn):
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn(conn)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
            return result

        return await self.run(work)

    # ----------------------------------------------------------------- meta
    async def meta_get(self, key, default=None):
        row = await self.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    async def meta_set(self, key, value):
        await self.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    # ------------------------------------------------------- backup / restore
    @property
    def total_changes(self) -> int:
        return self.conn.total_changes if self.conn else 0

    def snapshot(self, dest_path: str):
        """Consistent copy of the live database (uses SQLite's online backup API)."""
        with self._lock:
            dst = sqlite3.connect(dest_path)
            try:
                self.conn.backup(dst)
            finally:
                dst.close()

    def restore_from_file(self, src_path: str):
        """Replace the CONTENT of the live database with another database file."""
        with self._lock:
            src = sqlite3.connect(src_path)
            try:
                src.backup(self.conn)
            finally:
                src.close()
            self._migrate()  # in case the backup came from an older version

    async def table_counts(self):
        tables = ["recalls", "reaction_roles", "afk", "warnings", "polls", "players", "pokemon", "pokedex", "market"]

        def work(conn):
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in tables}

        return await self.run(work)


# ---------------------------------------------------------------------------
# PostgreSQL backend (a real hosted database: Neon, Supabase, Railway, ...)
# ---------------------------------------------------------------------------
# The rest of the bot is written once, in simple SQL. This layer translates the few
# SQLite-isms to PostgreSQL so both backends run the exact same bot code.
PG_PRIMARY_KEYS = {  # needed to turn "INSERT OR REPLACE" into a PostgreSQL upsert
    "species_data": ["id"],
    "incense": ["channel_id"],
}
PG_RETURNING_ID = ("pokemon", "warnings", "market")  # tables whose new row id we need (sqlite's lastrowid)


def pg_schema_statements(script=None):
    """A schema script converted to PostgreSQL (Discord IDs need BIGINT; ids use BIGSERIAL)."""
    sql = (script or SCHEMA_V1).replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    sql = re.sub(r"\bINTEGER\b", "BIGINT", sql)
    sql = re.sub(r"--[^\n]*", "", sql)  # drop comments
    return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]


def translate_sql(sql: str) -> str:
    """SQLite-flavoured SQL -> PostgreSQL."""
    s = sql.strip().rstrip(";")
    m = re.match(r"(?is)^INSERT\s+OR\s+IGNORE\s+INTO\s+(.*)$", s)
    if m:
        s = "INSERT INTO " + m.group(1) + " ON CONFLICT DO NOTHING"
    m = re.match(r"(?is)^INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]*)\)\s*(.*)$", s)
    if m:
        table, cols, rest = m.group(1), [c.strip() for c in m.group(2).split(",")], m.group(3)
        pk = PG_PRIMARY_KEYS[table]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in pk)
        s = f"INSERT INTO {table} ({', '.join(cols)}) {rest} ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {updates}"
    return s.replace("?", "%s")


class PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class PgConn:
    """Gives a psycopg connection the tiny sqlite3-style API the bot's code uses."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        pg = translate_sql(sql)
        want_id = re.match(r"(?is)^INSERT\s+INTO\s+(\w+)", pg) and re.match(r"(?is)^INSERT\s+INTO\s+(\w+)", pg).group(1) in PG_RETURNING_ID
        if want_id and "RETURNING" not in pg.upper():
            pg += " RETURNING id"
        cur = self._conn.execute(pg, tuple(params))
        if want_id:
            row = cur.fetchone()
            return PgCursor(cur, row["id"] if row else None)
        return PgCursor(cur)

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        cur.executemany(translate_sql(sql), [tuple(p) for p in seq])
        return PgCursor(cur)


class PostgresDatabase(Database):
    """Same interface as Database, but the data lives in a hosted PostgreSQL server."""

    kind = "postgres"

    def __init__(self, url: str):
        self.url = url
        self.path = self._safe_url(url)  # shown in logs: never includes the password
        self.conn = None
        self.fresh = False
        self._lock = threading.RLock()

    @staticmethod
    def _safe_url(url: str) -> str:
        return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)

    # ------------------------------------------------------------ connection
    def _open(self):
        import psycopg
        from psycopg.rows import dict_row

        # prepare_threshold=None: no cached query plans, so it also works behind a connection pooler (pgbouncer)
        self.conn = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=15, prepare_threshold=None)

    def _connect(self):
        self._open()
        self._migrate()

    def _migrate(self):
        c = PgConn(self.conn)
        c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = c.execute("SELECT value FROM meta WHERE key = ?", ("schema_version",)).fetchone()
        current = int(row["value"]) if row else 0
        for version in sorted(MIGRATIONS):
            if version > current:
                for stmt in pg_schema_statements(MIGRATIONS[version]):
                    c.execute(stmt)
                c.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    ("schema_version", str(version)),
                )
                current = version
        c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", ("created_at", str(int(time.time()))))
        self.conn.commit()

    async def close(self):
        def _close():
            with self._lock:
                if self.conn is not None:
                    try:
                        self.conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self.conn = None

        await asyncio.to_thread(_close)

    # --------------------------------------------------------------- queries
    def _run(self, fn):
        import psycopg

        with self._lock:
            for attempt in (1, 2):
                try:
                    if self.conn is None or self.conn.closed:
                        self._open()
                    try:
                        result = fn(PgConn(self.conn))
                        self.conn.commit()  # every call is one atomic transaction
                        return result
                    except BaseException:
                        try:
                            self.conn.rollback()
                        except Exception:  # noqa: BLE001
                            pass
                        raise
                except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                    # Hosted databases drop idle connections: reconnect once and redo the whole call
                    if attempt == 2:
                        raise
                    print(f"[DB] Connection lost ({type(e).__name__}); reconnecting...")
                    try:
                        if self.conn is not None:
                            self.conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self.conn = None

    async def transaction(self, fn):
        return await self.run(fn)  # _run already wraps every call in one transaction

    # ------------------------------------------------ sqlite-only features
    @property
    def total_changes(self) -> int:
        return 0

    def snapshot(self, dest_path: str):
        raise RuntimeError("Snapshots are for SQLite only: PostgreSQL hosts keep their own backups.")

    def restore_from_file(self, src_path: str):
        raise RuntimeError("Restore is for SQLite only.")


def create_database(default_path: str):
    """DATABASE_URL set -> PostgreSQL. Otherwise a local SQLite file (DB_PATH or ./data/scade.db)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        if url.startswith("postgres://"):  # some hosts still hand out the old scheme
            url = "postgresql://" + url[len("postgres://"):]
        return PostgresDatabase(url)
    return Database(os.environ.get("DB_PATH") or default_path)


# ---------------------------------------------------------------------------
# Backup file helpers (used by the Discord backup/restore code)
# ---------------------------------------------------------------------------
BACKUP_PREFIX = "scade-backup"


def compress_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return gzip.compress(f.read(), compresslevel=6)


def decompress_if_needed(data: bytes) -> bytes:
    if data[:2] == b"\x1f\x8b":  # gzip magic number
        return gzip.decompress(data)
    return data


def validate_sqlite_bytes(data: bytes, tmp_path: str) -> bool:
    """Write bytes to tmp_path and check that it is a healthy SCADE database."""
    with open(tmp_path, "wb") as f:
        f.write(data)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            conn.execute("SELECT 1 FROM meta LIMIT 1")  # raises if it isn't ours
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


async def restore_from_discord(bot, path: str, channel_id: int):
    """
    Called at start-up when the database file is missing. Looks in the backup
    channel for the newest backup made by this bot and writes it to `path`.
    Returns: "restored", "no_backup" or "failed".
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)  # fresh hosts have no data/ folder yet
        channel = await bot.fetch_channel(channel_id)
        async for msg in channel.history(limit=100):
            if msg.author.id != bot.user.id:
                continue
            for att in msg.attachments:
                name = att.filename.lower()
                if name.startswith(BACKUP_PREFIX) and (name.endswith(".db") or name.endswith(".db.gz")):
                    raw = await att.read()
                    data = decompress_if_needed(raw)
                    tmp = path + ".restore"
                    ok = await asyncio.to_thread(validate_sqlite_bytes, data, tmp)
                    if not ok:
                        print(f"[DB] Backup {att.filename} is damaged, trying an older one...")
                        continue
                    os.replace(tmp, path)
                    print(f"[DB] ✅ Restored database from Discord backup {att.filename}")
                    return "restored"
        return "no_backup"
    except Exception as e:  # noqa: BLE001
        print(f"[DB] ❌ Could not restore from the backup channel: {type(e).__name__}: {e}")
        return "failed"
