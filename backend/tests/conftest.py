from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        yield client


@pytest.fixture(scope='session')
def test_database_url() -> str:
    return os.getenv('KOSMO_TEST_DATABASE_URL', 'postgresql+asyncpg://kosmo:kosmo@localhost:5432/kosmo_test')


@pytest.fixture(scope='session')
def migrated_test_database(test_database_url: str) -> str:
    """Create the dedicated local test database when absent and migrate it."""
    parsed = urlsplit(test_database_url.replace('postgresql+asyncpg://', 'postgresql://', 1))
    database_name = parsed.path.lstrip('/')
    admin_url = urlunsplit((parsed.scheme, parsed.netloc, '/postgres', '', ''))
    connection = asyncpg.connect  # keep import explicit for asyncpg's driver

    import asyncio

    async def ensure_database() -> None:
        admin = await connection(admin_url)
        try:
            exists = await admin.fetchval('SELECT 1 FROM pg_database WHERE datname = $1', database_name)
            if not exists:
                await admin.execute(f'CREATE DATABASE "{database_name}"')
        finally:
            await admin.close()

    asyncio.run(ensure_database())
    env = os.environ | {'KOSMO_DATABASE_URL': test_database_url}
    import subprocess
    backend_dir = Path(__file__).resolve().parents[1]
    subprocess.run(['uv', 'run', 'alembic', 'upgrade', 'head'], cwd=backend_dir, env=env, check=True)
    return test_database_url
