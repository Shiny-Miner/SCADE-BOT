import asyncpg

# 🔴 Replace this with your real Supabase PostgreSQL URL
DB_URL = "https://cmvmnmfoutodoskumcbl.supabase.co"

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(dsn=DB_URL)

    async def add_points(self, user_id: int, amount: int = 1):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_points (user_id, points)
                VALUES ($1, $2)
                ON CONFLICT (user_id)
                DO UPDATE SET points = user_points.points + $2;
            """, user_id, amount)

    async def get_points(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT points FROM user_points WHERE user_id = $1", user_id)
            return row["points"] if row else 0
