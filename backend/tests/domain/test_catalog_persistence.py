"""Catalog persistence invariants; PostgreSQL is required for race/index proof."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_URL = os.getenv("KOSMO_CATALOG_TEST_DATABASE_URL", "")
MIGRATION_TEST_URL = os.getenv("KOSMO_TEST_DATABASE_URL", "postgresql+asyncpg://kosmo:kosmo@localhost:5432/kosmo_test")


def test_scope_name_ordered_references_and_secret_isolation_on_postgres(monkeypatch):
    """Exercise functional unique indexes, persisted list order and scope boundaries."""
    if not TEST_URL:
        pytest.skip("Set KOSMO_CATALOG_TEST_DATABASE_URL to a disposable, migrated PostgreSQL database")
    pytest.importorskip("asyncpg")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.domain.agents.models import Agent
    from app.domain.agents.repository import AgentRepository
    from app.domain.mcp_servers.models import McpServer
    from app.domain.mcp_servers.repository import McpServerRepository
    from app.domain.skills.models import Skill
    from app.domain.identity.models import User, UserRole
    from app.core.config import settings
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "config_encryption_key", Fernet.generate_key().decode())

    engine = create_async_engine(TEST_URL)

    async def exercise():
        factory = async_sessionmaker(engine, expire_on_commit=False)
        owner = str(uuid.uuid4())
        async with factory() as session:
            # This test must work on a blank database just upgraded through Alembic;
            # catalog owner FKs must not depend on seeded identity data.
            session.add(User(id=owner, username=f"catalog-persistence-{owner}",
                             password_hash="unused-test-hash", role=UserRole.admin))
            await session.flush()
            a = Agent(owner_user_id=owner, name="  Example ", visibility="personal", runtime="opencode",
                      model="default", instructions="", mcp_ids=["m2", "m1"], skill_ids=["s2", "s1"])
            repo = AgentRepository(session)
            await repo.create(a)
            agent_id = a.id
            assert (await repo.by_id(a.id)).mcp_ids == ["m2", "m1"]
            with pytest.raises(IntegrityError):
                await repo.create(Agent(owner_user_id=owner, name="example", visibility="personal",
                                        runtime="opencode", model="default", instructions=""))
            assert await repo.by_id(agent_id) is not None  # failed commit rolled back
            # Same name in a different scope and another catalog kind are valid.
            await repo.create(Agent(owner_user_id=owner, name="EXAMPLE", visibility="global",
                                    runtime="opencode", model="default", instructions=""))
            session.add(Skill(owner_user_id=owner, name="Example", visibility="personal", description="",
                              instructions=""))
            mcp_repo = McpServerRepository(session)
            mcp = await mcp_repo.create(McpServer(owner_user_id=owner, name="Example", visibility="personal",
                                                   transport_type="stdio", safe_config={"command": "tool"}),
                                        secret_values={"API_TOKEN": "secret-sentinel"})
            assert mcp.secret_ciphertext["API_TOKEN"] != "secret-sentinel"
            assert "secret-sentinel" not in str(mcp.safe_config)
        async def racing_insert(name):
            async with factory() as session:
                repo = AgentRepository(session)
                assert not await repo.name_conflict(owner, name, "personal", None)
                await asyncio.sleep(0.05)  # both prechecks complete before either insert
                try:
                    await repo.create(Agent(owner_user_id=owner, name=name, visibility="personal",
                                            runtime="opencode", model="default", instructions=""))
                    return True
                except IntegrityError:
                    return False

        assert sum(await asyncio.gather(racing_insert("Concurrent"), racing_insert("concurrent"))) == 1
        await engine.dispose()

    asyncio.run(exercise())


def test_fresh_model_registry_includes_identity_foreign_key_targets():
    """Importing each catalog model alone registers the identity FK targets."""
    script = """import importlib, sys
from app.core.db import Base
for name in sys.argv[1:]: importlib.import_module(name)
assert {'users', 'agents', 'mcp_servers', 'skills'} <= set(Base.metadata.tables)
"""
    subprocess.run([sys.executable, "-c", script,
                    "app.domain.agents.models", "app.domain.mcp_servers.models", "app.domain.skills.models"],
                   cwd=BACKEND_ROOT, check=True)


def test_0022_catalog_migration_upgrades_a_disposable_postgres_database():
    """Apply full migration chain in a unique database, never the configured app DB."""
    if os.name == "nt":
        pytest.skip("Run in backend container; host-to-container PostgreSQL resets on Windows")
    parsed = urlsplit(MIGRATION_TEST_URL.replace("postgresql+asyncpg://", "postgresql://", 1))
    admin_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", "", ""))
    database = f"kosmo_catalog_mig_{uuid.uuid4().hex[:12]}"
    env = os.environ | {"KOSMO_DATABASE_URL": f"postgresql+asyncpg://{parsed.netloc}/{database}"}

    async def prepare():
        connection = await asyncpg.connect(admin_url)
        try:
            await connection.execute(f'CREATE DATABASE "{database}"')
        finally:
            await connection.close()

    async def cleanup():
        connection = await asyncpg.connect(admin_url)
        try:
            await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await connection.close()

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Disposable PostgreSQL unavailable: {exc}")
    try:
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND_ROOT, env=env, check=True)
        async def verify():
            connection = await asyncpg.connect(f"postgresql://{parsed.netloc}/{database}")
            try:
                rows = await connection.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                assert {"agents", "mcp_servers", "skills"} <= {row["tablename"] for row in rows}
            finally:
                await connection.close()
        asyncio.run(verify())
    finally:
        asyncio.run(cleanup())
