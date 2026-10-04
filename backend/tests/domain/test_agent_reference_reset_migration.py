"""Destructive cutover proof on an isolated PostgreSQL database only."""
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
pytestmark = pytest.mark.skipif(os.name == "nt", reason="run in the backend container")


def test_0025_resets_workflow_data_and_preserves_identity_and_provider_rows():
    parsed = urlsplit(TEST_URL.replace("postgresql+asyncpg://", "postgresql://", 1))
    admin_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", "", ""))
    database = f"kosmo_wp17_{uuid.uuid4().hex[:12]}"
    database_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", "", ""))
    env = os.environ | {"KOSMO_DATABASE_URL": f"postgresql+asyncpg://{parsed.netloc}/{database}"}

    async def connect_admin():
        return await asyncpg.connect(admin_url)

    async def setup():
        connection = await connect_admin()
        try:
            await connection.execute(f'CREATE DATABASE "{database}"')
        finally:
            await connection.close()

    async def cleanup():
        connection = await connect_admin()
        try:
            await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        finally:
            await connection.close()

    def alembic(*args):
        subprocess.run(["uv", "run", "alembic", *args], cwd=BACKEND_ROOT, env=env, check=True)

    try:
        asyncio.run(setup())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
    try:
        alembic("upgrade", "0024_provider_runtime_v2")

        async def populate():
            conn = await asyncpg.connect(database_url)
            try:
                user, workflow, version, task = [str(uuid.uuid4()) for _ in range(4)]
                await conn.execute("INSERT INTO users (id,username,password_hash,role) VALUES ($1,$2,'hash','admin')", user, f"wp17-{user}")
                await conn.execute("INSERT INTO workflows (id,name) VALUES ($1,'legacy')", workflow)
                await conn.execute("INSERT INTO workflow_versions (id,workflow_id,version,definition,published_by) VALUES ($1,$2,1,'{}',$3)", version, workflow, user)
                await conn.execute("INSERT INTO activations (workflow_id,version_id) VALUES ($1,$2)", workflow, version)
                await conn.execute("INSERT INTO tasks (id,workflow_id,version_id,state,input_values,resolved_definition,created_by) VALUES ($1,$2,$3,'success','{}','{}',$4)", task, workflow, version, user)
                await conn.execute("INSERT INTO task_notes (id,task_id,revision,message_key,params) VALUES ($1,$2,1,'note','{}')", str(uuid.uuid4()), task)
                await conn.execute("INSERT INTO workflow_drafts (id,workflow_id,author_id,definition,layout) VALUES ($1,NULL,$2,'{}','{}')", str(uuid.uuid4()), user)
                await conn.execute("INSERT INTO provider_configs (id,user_id,provider,config_ciphertext,display_name) VALUES ($1,$2,'opencode','cipher','preserve')", str(uuid.uuid4()), user)
                return user
            finally:
                await conn.close()

        preserved_user = asyncio.run(populate())
        alembic("upgrade", "head")

        async def verify():
            conn = await asyncpg.connect(database_url)
            try:
                for table in ("tasks", "task_notes", "node_executions", "artifacts", "activations", "workflow_drafts", "workflow_versions", "workflows"):
                    assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0, table
                assert await conn.fetchval("SELECT count(*) FROM users WHERE id=$1", preserved_user) == 1
                assert await conn.fetchval("SELECT count(*) FROM provider_configs WHERE display_name='preserve' AND config_ciphertext='cipher'") == 1
            finally:
                await conn.close()

        asyncio.run(verify())
    finally:
        asyncio.run(cleanup())
