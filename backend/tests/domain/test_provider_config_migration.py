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


def _candidate_operation_columns(database_url: str) -> set[str]:
    return {row["column_name"] for row in _fetch(
        database_url,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'provider_candidate_operations'")}


def _insert_legacy_candidate_operation(database_url: str, user_id: str) -> None:
    """Insert a candidate operation row in the 0017 shape (no purpose state)."""
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def insert() -> None:
        connection = await asyncpg.connect(url)
        try:
            await connection.execute(
                "INSERT INTO users (id, username, password_hash, role) VALUES ($1, $2, $3, 'admin')",
                user_id, f"mig-{uuid.uuid4().hex[:10]}", "not-a-real-hash")
            await connection.execute(
                "INSERT INTO provider_candidate_operations (id, user_id, provider, payload_ciphertext, "
                "created_at, expires_at) VALUES ($1, $2, 'opencode', 'cipher', now(), now() + interval "
                "'120 seconds')",
                str(uuid.uuid4()), user_id)
        finally:
            await connection.close()

    asyncio.run(insert())


def test_0018_adds_purpose_and_verification_success_state():
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
        alembic("upgrade", "0017_provider_display_name")
        user_id = str(uuid.uuid4())
        _insert_legacy_candidate_operation(database_url, user_id)

        alembic("upgrade", "0020_workflow_name_ci")
        columns = {row["column_name"]: row for row in _fetch(
            database_url,
            "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'provider_candidate_operations'")}
        assert "purpose" in columns and "verification_succeeded" in columns
        assert columns["purpose"]["is_nullable"] == "NO"
        assert columns["verification_succeeded"]["is_nullable"] == "NO"
        # Pre-existing rows were discovery hand-offs and never succeeded a
        # recorded verification: both backfills are safe defaults.
        rows = _fetch(database_url, "SELECT purpose, verification_succeeded FROM provider_candidate_operations")
        assert rows and all(row["purpose"] == "discovery" and row["verification_succeeded"] is False
                            for row in rows)

        alembic("downgrade", "0017_provider_display_name")
        assert "purpose" not in _candidate_operation_columns(database_url)
        assert "verification_succeeded" not in _candidate_operation_columns(database_url)

        alembic("upgrade", "0020_workflow_name_ci")
        assert "purpose" in _candidate_operation_columns(database_url)
        assert "verification_succeeded" in _candidate_operation_columns(database_url)
    finally:
        asyncio.run(cleanup())


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
        alembic("upgrade", "0020_workflow_name_ci")
        columns = _provider_config_columns(database_url)
        assert "selected_model" not in columns
        assert "verification_status" in columns

        alembic("downgrade", "0015_candidate_operations")
        columns = _provider_config_columns(database_url)
        assert "selected_model" in columns
        assert "verification_status" in columns

        alembic("upgrade", "0020_workflow_name_ci")
        columns = _provider_config_columns(database_url)
        assert "selected_model" not in columns
        assert "verification_status" in columns
    finally:
        asyncio.run(cleanup())


def _insert_named_provider_configs(database_url: str, specs: list[tuple[str, str]]) -> str:
    """Insert rows in the 0018 shape (display_name exists) for one owner.

    Each spec is (provider, display_name); rows are personal (group_id NULL).
    Returns the owner user id.
    """
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def insert() -> str:
        connection = await asyncpg.connect(url)
        try:
            user_id = str(uuid.uuid4())
            await connection.execute(
                "INSERT INTO users (id, username, password_hash, role) VALUES ($1, $2, $3, 'admin')",
                user_id, f"mig-{uuid.uuid4().hex[:10]}", "not-a-real-hash")
            for index, (provider, display_name) in enumerate(specs, start=1):
                # Ascending explicit ids: the backfill keeps the first row (by
                # id) of each duplicate group unsuffixed.
                row_id = f"00000000-0000-0000-0000-{index:012d}"
                await connection.execute(
                    "INSERT INTO provider_configs (id, user_id, provider, config_ciphertext, display_name) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    row_id, user_id, provider, f"cipher-{index:08d}", display_name)
            return user_id
        finally:
            await connection.close()

    return asyncio.run(insert())


def _display_names(database_url: str) -> list[tuple[str, str]]:
    rows = _fetch(database_url, "SELECT provider, display_name FROM provider_configs "
                                "ORDER BY provider, display_name")
    return [(row["provider"], row["display_name"]) for row in rows]


def _index_names(database_url: str) -> set[str]:
    return {row["indexname"] for row in _fetch(
        database_url, "SELECT indexname FROM pg_indexes WHERE tablename = 'provider_configs'")}


def _constraint_names(database_url: str) -> set[str]:
    return {row["conname"] for row in _fetch(
        database_url, "SELECT conname FROM pg_constraint WHERE conrelid = 'provider_configs'::regclass")}


def test_0019_replaces_scope_uniqueness_with_case_insensitive_name_uniqueness():
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

    def alembic(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["uv", "run", "alembic", *arguments], cwd=BACKEND_ROOT,
                              env=env, check=check, capture_output=True, text=True)

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        alembic("upgrade", "0018_candidate_operation_purpose")
        user_id = _insert_named_provider_configs(database_url, [
            ("opencode", "Team Config"),
            ("opencode", "team config"),        # case-insensitive duplicate of row 1
            ("opencode", "Team Config (2)"),    # occupies the natural suffix slot
            ("other-provider", "Team Config"),  # different provider: never a conflict
        ])

        alembic("upgrade", "0020_workflow_name_ci")

        # Collision-safe deterministic backfill: the first row (by id) keeps
        # the name, the case-insensitive sibling is suffixed, and the suffix
        # search skips the pre-existing "Team Config (2)" name.
        names = {(provider, name) for provider, name in _display_names(database_url)}
        assert ("opencode", "Team Config") in names
        assert ("opencode", "Team Config (2)") in names
        assert ("other-provider", "Team Config") in names
        opencode_names = {name for provider, name in names if provider == "opencode"}
        assert len(opencode_names) == 3
        assert "team config (3)" in {name.lower() for name in opencode_names}

        # The one-row-per-scope rules are gone; the case-insensitive per-owner
        # name index is in place.
        assert "uq_provider_config_owner_provider_visibility_group" not in _constraint_names(database_url)
        assert "uq_provider_configs_global_provider" not in _index_names(database_url)
        assert "uq_provider_configs_group_provider" not in _index_names(database_url)
        assert "uq_provider_config_owner_provider_name_ci" in _index_names(database_url)

        # The index enforces the rule at the database level.
        url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

        async def insert_duplicate() -> None:
            connection = await asyncpg.connect(url)
            try:
                with pytest.raises(asyncpg.UniqueViolationError):
                    await connection.execute(
                        "INSERT INTO provider_configs (id, user_id, provider, config_ciphertext, display_name) "
                        "VALUES ($1, $2, 'opencode', 'cipher-x', 'TEAM CONFIG')",
                        str(uuid.uuid4()), user_id)
            finally:
                await connection.close()

        asyncio.run(insert_duplicate())

        # Downgrade refuses while same-scope instances exist...
        refused = alembic("downgrade", "0018_candidate_operation_purpose", check=False)
        assert refused.returncode != 0
        assert "uq_provider_config_owner_provider_name_ci" in _index_names(database_url)
        assert len(_display_names(database_url)) == 4

        # ...and succeeds once the data is representable again.
        url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

        async def remove_sibling() -> None:
            connection = await asyncpg.connect(url)
            try:
                # Keep exactly one opencode instance: the one-row-per-scope
                # rules of 0018 are representable again.
                await connection.execute(
                    "DELETE FROM provider_configs WHERE user_id = $1 AND provider = 'opencode' "
                    "AND lower(display_name) <> 'team config'",
                    user_id)
            finally:
                await connection.close()

        asyncio.run(remove_sibling())

        alembic("downgrade", "0018_candidate_operation_purpose")
        assert "uq_provider_config_owner_provider_name_ci" not in _index_names(database_url)
        assert "uq_provider_config_owner_provider_visibility_group" in _constraint_names(database_url)
        assert "uq_provider_configs_global_provider" in _index_names(database_url)
        assert "uq_provider_configs_group_provider" in _index_names(database_url)

        # Round-trip: the migration applies again on the downgraded database.
        alembic("upgrade", "0020_workflow_name_ci")
        assert "uq_provider_config_owner_provider_name_ci" in _index_names(database_url)
    finally:
        asyncio.run(cleanup())


def test_0019_downgrade_refuses_to_merge_same_scope_instances():
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

    def alembic(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["uv", "run", "alembic", *arguments], cwd=BACKEND_ROOT,
                              env=env, check=check, capture_output=True, text=True)

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        alembic("upgrade", "0018_candidate_operation_purpose")
        # Two distinctively-named personal instances for the same owner and
        # provider: representable at head, unrepresentable at 0018.
        _insert_named_provider_configs(database_url, [
            ("opencode", "Alpha"), ("opencode", "Beta"),
        ])
        alembic("upgrade", "0020_workflow_name_ci")

        refused = alembic("downgrade", "0018_candidate_operation_purpose", check=False)
        assert refused.returncode != 0
        # Nothing was merged or deleted: both rows and their ciphertexts are
        # intact and the refusal is transactional.
        rows = _fetch(database_url, "SELECT display_name, config_ciphertext FROM provider_configs "
                                    "ORDER BY display_name")
        assert [(row["display_name"], row["config_ciphertext"]) for row in rows] == [
            ("Alpha", rows[0]["config_ciphertext"]), ("Beta", rows[1]["config_ciphertext"])]
        assert "uq_provider_config_owner_provider_name_ci" in _index_names(database_url)
    finally:
        asyncio.run(cleanup())


def test_0019_backfill_suffixes_overlength_duplicates_within_column_limit():
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

    def alembic(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["uv", "run", "alembic", *arguments], cwd=BACKEND_ROOT,
                              env=env, check=check, capture_output=True, text=True)

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        alembic("upgrade", "0018_candidate_operation_purpose")
        _insert_named_provider_configs(database_url, [
            ("opencode", "A" * 80),
            ("opencode", "a" * 80),  # case-insensitive duplicate, also 80 chars
        ])
        url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

        async def mark_first_verified() -> None:
            connection = await asyncpg.connect(url)
            try:
                await connection.execute(
                    "UPDATE provider_configs SET verification_status = 'verified' "
                    "WHERE id = '00000000-0000-0000-0000-000000000001'")
            finally:
                await connection.close()

        asyncio.run(mark_first_verified())

        # Regression: the backfill used to append " (2)" to the 80-character
        # name and blew past the varchar(80) limit, failing the upgrade.
        alembic("upgrade", "0020_workflow_name_ci")

        rows = _fetch(database_url, "SELECT id, display_name, config_ciphertext, "
                                    "verification_status, visibility, group_id "
                                    "FROM provider_configs ORDER BY id")
        # The first row (by id) keeps its name; the sibling is renamed to a
        # distinct name that reserves room for the suffix inside the limit.
        assert [(row["display_name"], len(row["display_name"])) for row in rows] == [
            ("A" * 80, 80), ("a" * 76 + " (2)", 80)]
        # Identifiers, ciphertext, scopes and verification state are preserved.
        assert [row["id"] for row in rows] == [
            "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"]
        assert [row["config_ciphertext"] for row in rows] == ["cipher-00000001", "cipher-00000002"]
        assert [row["verification_status"] for row in rows] == ["verified", "unverified"]
        assert all(row["visibility"] == "personal" and row["group_id"] is None for row in rows)

        # Downgrade still refuses same-scope instances and loses nothing.
        refused = alembic("downgrade", "0018_candidate_operation_purpose", check=False)
        assert refused.returncode != 0
        assert _fetch(database_url, "SELECT id, display_name, config_ciphertext, "
                                    "verification_status, visibility, group_id "
                                    "FROM provider_configs ORDER BY id") == rows
    finally:
        asyncio.run(cleanup())


def test_0019_backfill_skips_occupied_truncated_suffix_slot():
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

    def alembic(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["uv", "run", "alembic", *arguments], cwd=BACKEND_ROOT,
                              env=env, check=check, capture_output=True, text=True)

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        alembic("upgrade", "0018_candidate_operation_purpose")
        _insert_named_provider_configs(database_url, [
            ("opencode", "A" * 80),
            ("opencode", "a" * 80),           # duplicate of row 1: must be renamed
            ("opencode", "A" * 76 + " (2)"),  # occupies the truncated " (2)" slot
        ])

        alembic("upgrade", "0020_workflow_name_ci")

        # The rename truncates the base to make room for the tag and skips the
        # already-occupied " (2)" slot, landing on " (3)".
        names = {row["id"]: row["display_name"] for row in _fetch(
            database_url, "SELECT id, display_name FROM provider_configs")}
        assert names == {
            "00000000-0000-0000-0000-000000000001": "A" * 80,
            "00000000-0000-0000-0000-000000000002": "a" * 76 + " (3)",
            "00000000-0000-0000-0000-000000000003": "A" * 76 + " (2)",
        }
        assert all(len(name) <= 80 for name in names.values())
        assert len({name.lower() for name in names.values()}) == len(names)
    finally:
        asyncio.run(cleanup())


def test_0019_backfill_collision_checks_the_final_truncated_value():
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

    def alembic(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["uv", "run", "alembic", *arguments], cwd=BACKEND_ROOT,
                              env=env, check=check, capture_output=True, text=True)

    try:
        asyncio.run(prepare())
    except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    try:
        alembic("upgrade", "0018_candidate_operation_purpose")
        # Two duplicate pairs of 80-character names. Both renames truncate to
        # the same "a"*76 prefix, so the second pair's " (2)" candidate would
        # collide with the first pair's assigned rename unless collisions are
        # checked against the final truncated value.
        _insert_named_provider_configs(database_url, [
            ("opencode", "A" * 80),
            ("opencode", "a" * 80),
            ("opencode", "A" * 79 + "Z"),
            ("opencode", "a" * 79 + "z"),
        ])

        alembic("upgrade", "0020_workflow_name_ci")

        names = {row["id"]: row["display_name"] for row in _fetch(
            database_url, "SELECT id, display_name FROM provider_configs")}
        assert names == {
            "00000000-0000-0000-0000-000000000001": "A" * 80,
            "00000000-0000-0000-0000-000000000002": "a" * 76 + " (2)",
            "00000000-0000-0000-0000-000000000003": "A" * 79 + "Z",
            "00000000-0000-0000-0000-000000000004": "a" * 76 + " (3)",
        }
        assert all(len(name) <= 80 for name in names.values())
        assert len({name.lower() for name in names.values()}) == len(names)
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

        alembic("upgrade", "0020_workflow_name_ci")
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

        alembic("upgrade", "0020_workflow_name_ci")
        assert "display_name" in _provider_config_columns(database_url)
    finally:
        asyncio.run(cleanup())
