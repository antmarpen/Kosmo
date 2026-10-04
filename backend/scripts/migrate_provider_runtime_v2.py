"""Convert encrypted OpenCode v1 provider rows to the v2 file contract.

Run only during an approved maintenance window against a verified encrypted
database backup. The command never prints file contents or ciphertext.
"""
import argparse
import asyncio
import json
import os
import uuid
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.provider_configs.models import ProviderCandidateOperation, ProviderConfig


class ConversionError(ValueError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _safe_json(data: bytes):
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ConversionError("malformed_json") from None


def convert_files(config_bytes: bytes, auth_bytes: bytes | None, row_id: str) -> tuple[bytes, bytes | None]:
    config = _safe_json(config_bytes)
    if not isinstance(config, dict):
        raise ConversionError("unsupported_config")
    if "providers" in config:
        provider_map = config.get("providers")
    elif "provider" in config:
        provider_map = config.pop("provider")
        if set(config) - {"model", "$schema"}:
            raise ConversionError("unknown_config_fields")
    else:
        raise ConversionError("unsupported_config")
    if not isinstance(provider_map, dict) or not provider_map:
        raise ConversionError("unsupported_config")
    config["providers"] = provider_map

    auth_object = {} if auth_bytes is None else _safe_json(auth_bytes)
    if not isinstance(auth_object, dict):
        raise ConversionError("unsupported_auth")
    auth_entries = []
    for integration_id, credential in auth_object.items():
        if not isinstance(integration_id, str) or not isinstance(credential, dict):
            raise ConversionError("unsupported_auth")
        kind = credential.get("type")
        if kind == "api":
            key = credential.get("key")
            if not isinstance(key, str) or not key:
                raise ConversionError("unsupported_auth_type")
            value = {"type": "key", "key": key}
        elif kind == "oauth":
            access, refresh, expires = credential.get("access"), credential.get("refresh"), credential.get("expires")
            if not all(isinstance(item, str) and item for item in (access, refresh)) or not isinstance(expires, (int, float)):
                raise ConversionError("unsupported_auth_type")
            metadata = {key: item for key, item in credential.items()
                        if key not in {"type", "access", "refresh", "expires", "methodID"}}
            value = {"type": "oauth", "methodID": credential.get("methodID") or integration_id,
                     "refresh": refresh, "access": access, "expires": int(expires), "metadata": metadata}
        else:
            raise ConversionError("unsupported_auth_type")
        auth_entries.append({"id": f"cred_{uuid.uuid4().hex}", "integrationID": integration_id,
                             "label": "API key", "active": True, "value": value})

    # A v1 inline apiKey is converted only if it does not collide with a
    # separate auth credential for the same integration.
    for integration_id, definition in provider_map.items():
        if not isinstance(definition, dict):
            raise ConversionError("unsupported_provider")
        options = definition.get("options", {})
        if not isinstance(options, dict):
            raise ConversionError("unsupported_provider")
        inline = options.get("apiKey")
        if inline is None:
            continue
        if not isinstance(inline, str) or not inline:
            raise ConversionError("unsupported_inline_credential")
        if any(entry["integrationID"] == integration_id for entry in auth_entries):
            raise ConversionError("credential_conflict")
        options = dict(options)
        options.pop("apiKey")
        definition["options"] = options
        auth_entries.append({"id": f"cred_{uuid.uuid4().hex}", "integrationID": integration_id,
                             "label": "API key", "active": True,
                             "value": {"type": "key", "key": inline}})

    encoded_config = json.dumps(config, separators=(",", ":")).encode()
    encoded_auth = json.dumps(auth_entries, separators=(",", ":")).encode() if auth_entries else None
    return encoded_config, encoded_auth


@dataclass
class Summary:
    converted: int = 0
    already_v2: int = 0
    failures: dict[str, int] | None = None
    converted_ids: list[str] | None = None
    failure_ids: dict[str, list[str]] | None = None


async def migrate(*, dry_run: bool, database_url: str, encryption_key: str) -> Summary:
    try:
        fernet = Fernet(encryption_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise ConversionError("encryption_key_invalid") from None
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    summary = Summary(failures={}, converted_ids=[], failure_ids={})

    def fail(category: str, row_id: str) -> None:
        summary.failures[category] = summary.failures.get(category, 0) + 1
        summary.failure_ids.setdefault(category, []).append(row_id)
    try:
        async with sessions() as session:
            ids = list((await session.scalars(select(ProviderConfig.id).order_by(ProviderConfig.id))).all())
        for row_id in ids:
            async with sessions() as session:
                async with session.begin():
                    row = await session.scalar(select(ProviderConfig).where(
                        ProviderConfig.id == row_id).with_for_update())
                    if row is None:
                        fail("concurrent_change", row_id)
                        continue
                    if row.format == "v2":
                        summary.already_v2 += 1
                        continue
                    try:
                        config_plain = fernet.decrypt(row.config_ciphertext.encode("ascii"))
                        auth_plain = fernet.decrypt(row.auth_ciphertext.encode("ascii")) if row.auth_ciphertext else None
                        config, auth = convert_files(config_plain, auth_plain, row.id)
                        new_config = fernet.encrypt(config).decode("ascii")
                        new_auth = fernet.encrypt(auth).decode("ascii") if auth is not None else None
                    except (InvalidToken, UnicodeEncodeError):
                        fail("encryption_key_failure", row_id)
                        continue
                    except ConversionError as exc:
                        fail(exc.category, row_id)
                        continue
                    if dry_run:
                        summary.converted += 1
                        summary.converted_ids.append(row_id)
                        continue
                    result = await session.execute(update(ProviderConfig).where(
                        ProviderConfig.id == row.id, ProviderConfig.format == row.format,
                        ProviderConfig.config_ciphertext == row.config_ciphertext,
                        ProviderConfig.auth_ciphertext.is_not_distinct_from(row.auth_ciphertext),
                    ).values(config_ciphertext=new_config, auth_ciphertext=new_auth,
                             format="v2", verification_status="unverified", updated_at=row.updated_at))
                    if result.rowcount != 1:
                        fail("concurrent_change", row_id)
                        continue
                    summary.converted += 1
                    summary.converted_ids.append(row_id)
            
        if not dry_run:
            async with sessions.begin() as session:
                await session.execute(delete(ProviderCandidateOperation))
        return summary
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report eligible rows without writing (default)")
    mode.add_argument("--apply", action="store_true", help="Apply conversions; use only after maintenance approval")
    args = parser.parse_args()
    url = os.getenv("KOSMO_DATABASE_URL")
    key = os.getenv("KOSMO_CONFIG_ENCRYPTION_KEY")
    if not url or not key:
        parser.error("KOSMO_DATABASE_URL and KOSMO_CONFIG_ENCRYPTION_KEY must be configured")
    dry_run = not args.apply
    summary = asyncio.run(migrate(dry_run=dry_run, database_url=url, encryption_key=key))
    print(json.dumps({"dry_run": dry_run, "converted": summary.converted,
                      "converted_ids": summary.converted_ids or [], "already_v2": summary.already_v2,
                      "failures": summary.failures or {}, "failure_ids": summary.failure_ids or {}}, sort_keys=True))
    if summary.failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
