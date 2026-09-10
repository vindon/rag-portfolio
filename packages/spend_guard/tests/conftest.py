from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from spend_guard.schema import apply_schema

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vinoth@localhost:5432/spend_guard_test"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _admin_dsn_and_db_name() -> tuple[str, str]:
    parts = urlsplit(TEST_DATABASE_URL)
    db_name = parts.path.lstrip("/")
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    return admin_dsn, db_name


async def _ensure_database_exists() -> None:
    admin_dsn, db_name = _admin_dsn_and_db_name()
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


async def _apply_schema() -> None:
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await apply_schema(conn)
    finally:
        await conn.close()


def pytest_configure(config: pytest.Config) -> None:
    asyncio.run(_ensure_database_exists())
    asyncio.run(_apply_schema())
