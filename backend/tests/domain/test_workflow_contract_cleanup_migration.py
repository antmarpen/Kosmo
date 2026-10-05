"""Destructive workflow cleanup migration tests use an isolated PostgreSQL DB.

Run on Windows inside the backend container:
`docker compose exec -T backend sh -c "KOSMO_TEST_DATABASE_URL=postgresql+asyncpg://kosmo:kosmo@postgres:5432/kosmo_test uv run pytest tests/domain/test_workflow_contract_cleanup_migration.py -q"`
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
pytestmark = pytest.mark.skipif(os.name == "nt", reason="run in backend container; host DB connections reset on Windows")


def test_0021_deletes_only_deprecated_workflows_and_is_idempotent():
    parsed = urlsplit(TEST_URL.replace("postgresql+asyncpg://", "postgresql://", 1))
    admin_url = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", "", ""))
    database = f"kosmo_test_mig_{uuid.uuid4().hex[:12]}"
    database_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", "", ""))
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

    def alembic(*args):
        subprocess.run(["uv", "run", "alembic", *args], cwd=BACKEND_ROOT, env=env, check=True)

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    try:
        alembic("upgrade", "0020_workflow_name_ci")
        user, old_wf, new_wf = [str(uuid.uuid4()) for _ in range(3)]
        old_version, new_version, old_task, new_task = [str(uuid.uuid4()) for _ in range(4)]
        async def insert_data():
            connection = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
            try:
                await connection.execute("INSERT INTO users (id, username, password_hash, role) VALUES ($1,$2,'x','admin')", user, f"migration-{uuid.uuid4().hex}")
                await connection.execute("INSERT INTO workflows (id,name) VALUES ($1,'old'),($2,'new')", old_wf, new_wf)
                old_def = '{"nodes":[{"label_message_key":"deprecated"}]}'
                new_def = '{"nodes":[{"label":"Current"}]}'
                for wf, version, definition in ((old_wf, old_version, old_def), (new_wf, new_version, new_def)):
                    await connection.execute("INSERT INTO workflow_versions (id,workflow_id,version,definition,published_by) VALUES ($1,$2,1,$3::jsonb,$4)", version,wf,definition,user)
                    await connection.execute("INSERT INTO workflow_drafts (id,workflow_id,author_id,definition,layout) VALUES ($1,$2,$3,$4::jsonb,'{}')", str(uuid.uuid4()),wf,user,definition)
                await connection.execute("INSERT INTO activations (workflow_id,version_id) VALUES ($1,$2),($3,$4)",old_wf,old_version,new_wf,new_version)
                for task, wf, version, definition in ((old_task,old_wf,old_version,old_def),(new_task,new_wf,new_version,new_def)):
                    await connection.execute("INSERT INTO tasks (id,workflow_id,version_id,state,input_values,resolved_definition,created_by) VALUES ($1,$2,$3,'complete','{}'::jsonb,$4::jsonb,$5)",task,wf,version,definition,user)
                for table, fields in (("task_notes", "id,task_id,revision,message_key,params"),):
                    await connection.execute("INSERT INTO task_notes (id,task_id,revision,message_key,params) VALUES ($1,$2,1,'note','{}'::jsonb),($3,$4,1,'note','{}'::jsonb)",str(uuid.uuid4()),old_task,str(uuid.uuid4()),new_task)
                for task in (old_task, new_task):
                    await connection.execute("INSERT INTO node_executions (id,task_id,node_id,iteration,attempt,state) VALUES ($1,$2,'node',0,1,'complete')", str(uuid.uuid4()), task)
                    await connection.execute("INSERT INTO artifacts (id,task_id,node_id,logical_name,iteration,attempt,media_type,size,sha256,storage_path) VALUES ($1,$2,'node','output',0,1,'text/plain',1,'hash','path')", str(uuid.uuid4()), task)
                await connection.execute("INSERT INTO provider_configs (id,user_id,provider,config_ciphertext,display_name) VALUES ($1,$2,'opencode','cipher','Keep')",str(uuid.uuid4()),user)
            finally:
                await connection.close()
        asyncio.run(insert_data())
        # Pin to 0021: later migrations (notably 0025's destructive reset) remove
        # workflow data, which is out of scope for this 0021 cleanup test.
        alembic("upgrade", "0021_editor_contract_cleanup")
        alembic("upgrade", "0021_editor_contract_cleanup")
        async def assert_state():
            connection = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://", 1))
            try:
                for table in ("workflows", "workflow_versions", "workflow_drafts", "activations", "tasks", "task_notes", "node_executions", "artifacts"):
                    counts = await connection.fetch(f"SELECT count(*) AS n FROM {table}")
                    expected = 1  # the surviving non-deprecated workflow's aggregate
                    assert counts[0]["n"] == expected, table
                assert await connection.fetchval("SELECT count(*) FROM provider_configs WHERE display_name='Keep'") == 1
                assert await connection.fetchval("SELECT count(*) FROM tasks WHERE id=$1", new_task) == 1
            finally:
                await connection.close()
        asyncio.run(assert_state())
    finally:
        asyncio.run(cleanup())
