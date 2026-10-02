"""Migration contract tests for case-insensitive workflow-name uniqueness.

Runs the real alembic chain against a throwaway PostgreSQL database so 0020
stays consistent with the SQLAlchemy models: the exact-name unique constraint
is replaced by a functional unique index on lower(name), pre-existing
case-variant rows are suffixed deterministically (first row by id keeps its
name), nothing is deleted or merged, and existing rows stay usable through
the application's own repository afterwards. The downgrade restores the
exact-name constraint and the upgrade applies again (round trip).

NOTE: host→localhost:5432 connections reset on this Windows host (documented
quirk), so run this file inside the backend container where postgres:5432 is
stable: `docker compose exec -T backend sh -c "KOSMO_TEST_DATABASE_URL=
'postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test' uv run pytest
tests/domain/test_workflow_name_migration.py -q"`. Skipped on the Windows
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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.workflows.repository import WorkflowRepository

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_URL = os.getenv("KOSMO_TEST_DATABASE_URL", "postgresql+asyncpg://kosmo:kosmo@localhost:5432/kosmo_test")

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="host→container DB connections reset on Windows (documented quirk); "
           "run inside the backend container — see module docstring",
)


def _fetch(database_url: str, query: str) -> list[dict]:
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def fetch() -> list[dict]:
        connection = await asyncpg.connect(url)
        try:
            return [dict(row) for row in await connection.fetch(query)]
        finally:
            await connection.close()

    return asyncio.run(fetch())


def _insert_legacy_workflows(database_url: str, names: list[str]) -> list[str]:
    """Insert workflows in the 0019 shape (exact-name uniqueness only), with
    ascending explicit ids so the backfill's first-row-by-id choice is
    deterministic. Returns the inserted ids in name order."""
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def insert() -> list[str]:
        connection = await asyncpg.connect(url)
        try:
            user_id = str(uuid.uuid4())
            await connection.execute(
                "INSERT INTO users (id, username, password_hash, role) VALUES ($1, $2, $3, 'admin')",
                user_id, f"mig-{uuid.uuid4().hex[:10]}", "not-a-real-hash")
            ids = []
            for index, name in enumerate(names, start=1):
                row_id = f"00000000-0000-0000-0000-{index:012d}"
                await connection.execute(
                    "INSERT INTO workflows (id, name) VALUES ($1, $2)", row_id, name)
                # A draft and a published version hang off the first row so the
                # test can prove migrated rows stay fully usable.
                if index == 1:
                    await connection.execute(
                        "INSERT INTO workflow_versions (id, workflow_id, version, definition, published_by) "
                        "VALUES ($1, $2, 1, $3::jsonb, $4)",
                        str(uuid.uuid4()), row_id, '{"schema_version":"v1"}', user_id)
                    await connection.execute(
                        "INSERT INTO workflow_drafts (id, workflow_id, author_id, definition, layout) "
                        "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)",
                        str(uuid.uuid4()), row_id, user_id, '{}', '{}')
                ids.append(row_id)
            return ids
        finally:
            await connection.close()

    return asyncio.run(insert())


def _workflow_names(database_url: str) -> dict[str, str]:
    return {row["id"]: row["name"] for row in _fetch(
        database_url, "SELECT id, name FROM workflows")}


def _index_names(database_url: str) -> set[str]:
    return {row["indexname"] for row in _fetch(
        database_url, "SELECT indexname FROM pg_indexes WHERE tablename = 'workflows'")}


def _constraint_names(database_url: str) -> set[str]:
    return {row["conname"] for row in _fetch(
        database_url, "SELECT conname FROM pg_constraint WHERE conrelid = 'workflows'::regclass")}


def test_0020_replaces_exact_name_uniqueness_with_case_insensitive_uniqueness():
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

    long_name = "L" * 200
    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        alembic("upgrade", "0019_provider_config_instances")
        first_id, second_id, third_id, other_id, long_id, long_twin_id = _insert_legacy_workflows(database_url, [
            "Billing",            # first of its case-variant group: keeps the name
            "billing",            # case-insensitive sibling → suffixed
            "BILLING",            # case-insensitive sibling → suffixed
            "Other flow",         # no conflict: untouched
            long_name,            # column-limit case: the suffix must still fit String(200)
            long_name.lower(),    # case-insensitive sibling of the long name
        ])

        alembic("upgrade", "head")

        # Deterministic, non-destructive backfill: the first row (by id) of
        # each duplicate group keeps its name, later siblings take the first
        # free "Name (N)" suffix, and unrelated rows are untouched.
        names = _workflow_names(database_url)
        assert names[first_id] == "Billing"
        assert names[second_id].lower() == "billing (2)"
        assert names[third_id].lower() == "billing (3)"
        assert names[other_id] == "Other flow"
        assert names[long_id] == long_name
        assert names[long_twin_id] == long_name.lower()[:196] + " (2)"
        assert len(names[long_twin_id]) == 200
        # Nothing was deleted or merged: all six rows survive.
        assert len(names) == 6

        # The exact-name constraint is gone; the case-insensitive index is in
        # place and enforces the rule at the database level.
        assert "workflows_name_key" not in _constraint_names(database_url)
        assert "uq_workflows_name_ci" in _index_names(database_url)
        url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

        async def insert_case_variant() -> None:
            connection = await asyncpg.connect(url)
            try:
                with pytest.raises(asyncpg.UniqueViolationError):
                    await connection.execute(
                        "INSERT INTO workflows (id, name) VALUES ($1, $2)",
                        str(uuid.uuid4()), "BiLlInG")
            finally:
                await connection.close()

        asyncio.run(insert_case_variant())

        # Existing rows stay usable through the application's own repository:
        # the survivor is found case-insensitively, its draft/version still
        # resolve, and renaming it works.
        engine = create_async_engine(f"postgresql+asyncpg://{parsed.netloc}/{database}", poolclass=NullPool)

        async def use_repository() -> str:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                repository = WorkflowRepository(db)
                conflict = await repository.find_name_conflict("billing")
                assert conflict is not None and conflict.id == first_id
                workflow = await repository.get_workflow(first_id)
                assert workflow is not None and workflow.name == "Billing"
                version = await repository.get_latest_version(first_id)
                assert version is not None and version.version == 1
                renamed = await repository.rename_workflow(first_id, "Billing Renamed")
                assert renamed is not None and renamed.name == "Billing Renamed"
                # The repository only flushes; the route layer commits, so the
                # test owns that boundary here.
                await db.commit()
                return renamed.name

        try:
            assert asyncio.run(use_repository()) == "Billing Renamed"
        finally:
            asyncio.run(engine.dispose())
        names = _workflow_names(database_url)
        assert names[first_id] == "Billing Renamed"

        # Downgrade restores the exact-name constraint (always representable:
        # the backfill left every name distinct even case-insensitively)...
        alembic("downgrade", "0019_provider_config_instances")
        assert "workflows_name_key" in _constraint_names(database_url)
        assert "uq_workflows_name_ci" not in _index_names(database_url)
        assert len(_workflow_names(database_url)) == 6

        # ...and the upgrade applies again on the downgraded database.
        alembic("upgrade", "head")
        assert "uq_workflows_name_ci" in _index_names(database_url)
        assert "workflows_name_key" not in _constraint_names(database_url)
    finally:
        asyncio.run(cleanup())
