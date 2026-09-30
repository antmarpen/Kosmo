"""Application settings loaded from environment variables.

All settings use the ``KOSMO_`` env prefix (for example ``KOSMO_DATABASE_URL``).
``.env.example`` at the repository root documents the host-side values; the
Docker Compose stack injects the container-internal values itself and does not
require an ``.env`` file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, 12-factor application settings."""

    model_config = SettingsConfigDict(env_prefix="KOSMO_", env_file=".env", extra="ignore")

    test_database_url: str = "postgresql+asyncpg://kosmo:kosmo@localhost:5432/kosmo_test"

    # PostgreSQL as a SQLAlchemy async URL; the app database is `kosmo`.
    database_url: str = "postgresql+asyncpg://kosmo:kosmo@localhost:5432/kosmo"

    # Temporal frontend (gRPC) endpoint and namespace.
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "kosmo-tasks"

    max_main_tasks: int = 3
    max_agents: int = 2

    # Placeholder value â€” real secret handling lands with identity (WP-05).
    # Never commit a real secret; override via the environment per deployment.
    jwt_secret: str = ""

    # Dedicated Fernet key for provider runtime configuration. Required only
    # when uploading/decrypting a provider config; never commit a real value.
    config_encryption_key: str = ""


settings = Settings()


