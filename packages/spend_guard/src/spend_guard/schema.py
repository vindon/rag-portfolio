from __future__ import annotations

from importlib import resources

import asyncpg

SCHEMA_SQL = resources.files("spend_guard").joinpath("schema.sql").read_text()


async def apply_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(SCHEMA_SQL)
