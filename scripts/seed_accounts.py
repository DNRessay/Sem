import asyncio
import json
import os
import sys
import time

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateway.auth import hash_passphrase  # noqa: E402


async def main():
    database_url = os.environ["NEON_DATABASE_URL"]
    # A JSON array so more accounts can be added later just by editing this
    # secret's value and re-running the workflow — no code or redeploy needed.
    # e.g. [{"id": "owner", "passphrase": "...", "role": "owner"},
    #       {"id": "someone-else", "passphrase": "...", "role": "guest"}]
    accounts = json.loads(os.environ["OWNER_ACCOUNTS_JSON"])

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            """CREATE TABLE IF NOT EXISTS accounts (
                   id TEXT PRIMARY KEY,
                   passphrase_hash TEXT NOT NULL,
                   role TEXT NOT NULL DEFAULT 'owner',
                   created_at BIGINT NOT NULL
               )"""
        )
        for account in accounts:
            passphrase_hash = hash_passphrase(account["passphrase"])
            await conn.execute(
                """INSERT INTO accounts (id, passphrase_hash, role, created_at)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (id) DO UPDATE SET passphrase_hash=$2, role=$3""",
                account["id"], passphrase_hash, account.get("role", "owner"), int(time.time()),
            )
    finally:
        await conn.close()

    # IDs and roles only, never the passphrase — this log is visible in a public repo's Actions tab.
    print(f"Seeded accounts: {[(a['id'], a.get('role', 'owner')) for a in accounts]}")


asyncio.run(main())
