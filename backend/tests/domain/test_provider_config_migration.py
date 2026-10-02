"""Migration contract tests for provider configurations.

Runs the real alembic chain against a throwaway PostgreSQL database so the
migration upgrade/downgrade pairs stay consistent with the SQLAlchemy models:
0016 must leave provider_configs without selected_model (keeping
verification_status) and 0017 must add a NOT NULL display_name backfilled
from the provider type for pre-existing rows.

NOTE: host→localhost:5432 connections reset on this Windows host (documented
quirk), so run this file inside the backend container where postgres:5432 is
stable: `docker compose exec -T backend sh -c "KOSMO_TEST_DATABASE_URL=
'postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' uv run pytest
tests/domain/test_provider_config_migration.py -q"`. Skipped on the Windows
host for that reason.
"""

import asyncio
import os
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_URL = os.getenv("KOSMO_TEST_DATABASE_URL", "postgresql+asyncpg://kosmo:kosmo@localhost:5432/kosmo_test")

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)


def _provider_config_columns(database_url: str) -> set[str]:
    return {row["column_name"] for row in _fetch(
        database_url,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'provider_configs'")}


def _fetch(database_url: str, query: str) -> list[dict]:
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def fetch() -> list[dict]:
        connection = await asyncpg.connect(url)
        try:
            return [dict(row) for row in await connection.fetch(query)]
        finally:
            await connection.close()

    return asyncio.run(fetch())


def _insert_legacy_provider_configs(database_url: str) -> None:
    """Insert rows in the 0016 shape (before display_name existed)."""
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def insert() -> None:
        connection = await asyncpg.connect(url)
        try:
            user_id = str(uuid.uuid4())
            await connection.execute(
                "INSERT INTO users (id, username, password_hash, role) VALUES ($1, $2, $3, 'admin')",
                user_id, f"mig-{uuid.uuid4().hex[:10]}", "not-a-real-hash")
            for index, provider in enumerate(("opencode", "other-provider")):
                await connection.execute(
                    "INSERT INTO provider_configs (id, user_id, provider, config_ciphertext) "
                    "VALUES ($1, $2, $3, $4)",
                    str(uuid.uuid4()), user_id, provider, f"cipher-{index}")
        finally:
            await connection.close()

    asyncio.run(insert())


def test_0016_drops_selected_model_and_upgrade_downgrade_roundtrips():
    parsed = urlsplit(TEST_URL.replace("postgresql+asyncpg://", "postgresql://", 1))
    admin_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", "", ""))
    database = f"kosmo_test_mig_{uuid.uuid4().hex[:12]}"
    database_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", "", ""))
    env = os.environ | {"KOSMO_DATABASE_URL": f"postgresql+asyncpg://{parsed.netloc}/{database}"}

    async def prepare() -> None:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'CREATE DATABASE "{database}"')
        finally:
            await admin.close()

    async def cleanup() -> None:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    def alembic(*arguments: str) -> None:
        subprocess.run(["uv", "run", "alembic", *arguments], cwd=BACKEND_ROOT, env=env, check=True)

    try:
        alembic("upgrade", "head")
        columns = _provider_config_columns(database_url)
        assert "selected_model" not in columns
        assert "verification_status" in columns

        alembic("downgrade", "0015_candidate_operations")
        columns = _provider_config_columns(database_url)
        assert "selected_model" in columns
        assert "verification_status" in columns

        alembic("upgrade", "head")
        columns = _provider_config_columns(database_url)
        assert "selected_model" not in columns
        assert "verification_status" in columns
    finally:
        asyncio.run(cleanup())


def test_0017_adds_not_null_display_name_backfilled_from_provider():
    parsed = urlsplit(TEST_URL.replace("postgresql+asyncpg://", "postgresql://", 1))
    admin_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", "", ""))
    database = f"kosmo_test_mig_{uuid.uuid4().hex[:12]}"
    database_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", "", ""))
    env = os.environ | {"KOSMO_DATABASE_URL": f"postgresql+asyncpg://{parsed.netloc}/{database}"}

    async def prepare() -> None:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'CREATE DATABASE "{database}"')
        finally:
            await admin.close()

    async def cleanup() -> None:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await admin.close()

    def alembic(*arguments: str) -> None:
        subprocess.run(["uv", "run", "alembic", *arguments], cwd=BACKEND_ROOT, env=env, check=True)

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        alembic("upgrade", "0016_drop_selected_model")
        assert "display_name" not in _provider_config_columns(database_url)
        _insert_legacy_provider_configs(database_url)

        alembic("upgrade", "head")
        columns = {row["column_name"]: row["is_nullable"] for row in _fetch(
            database_url,
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'provider_configs'")}
        assert "display_name" in columns
        # No default and no NULLs: every row must carry a real name.
        assert columns["display_name"] == "NO"
        rows = _fetch(database_url, "SELECT provider, display_name FROM provider_configs")
        assert len(rows) == 2
        # Pre-existing rows are backfilled from the provider type; new rows
        # always carry a user-entered name instead.
        assert all(row["display_name"] == row["provider"] for row in rows)

        alembic("downgrade", "0016_drop_selected_model")
        assert "display_name" not in _provider_config_columns(database_url)

        alembic("upgrade", "head")
        assert "display_name" in _provider_config_columns(database_url)
    finally:
        asyncio.run(cleanup())
