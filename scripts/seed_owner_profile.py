import asyncio
import json
import os
import time

import asyncpg


async def main():
    database_url = os.environ["NEON_DATABASE_URL"]
    profile = json.loads(os.environ["OWNER_PROFILE_JSON"])

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS user_models (
                   session_id TEXT PRIMARY KEY,
                   data JSONB NOT NULL,
                   updated_at BIGINT NOT NULL
               )"""
        )
        await conn.execute(
            """INSERT INTO user_models (session_id, data, updated_at)
               VALUES ('owner', $1, $2)
               ON CONFLICT (session_id) DO UPDATE SET data = $1, updated_at = $2""",
            json.dumps(profile), int(time.time()),
        )
    finally:
        await conn.close()

    # Keys only, never values — this log is visible in a public repo's Actions tab.
    print(f"Seeded owner profile with keys: {sorted(profile.keys())}")


asyncio.run(main())
