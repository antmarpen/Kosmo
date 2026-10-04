import asyncio
import json

import pytest
from cryptography.fernet import Fernet

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from app.domain.provider_configs.service import ProviderConfigService
from shared.errors import ValidationFailedError


class CandidateRepository:
    def __init__(self):
        self.rows = {}

    async def create_candidate_operation(self, user_id, provider, ciphertext, expires_at, *, purpose):
        row_id = str(len(self.rows))
        self.rows[row_id] = CandidateRow(id=row_id, user_id=user_id, provider=provider,
                                         payload_ciphertext=ciphertext, expires_at=expires_at,
                                         purpose=purpose, verification_succeeded=False)
        return self.rows[row_id]

    async def get_candidate_operation(self, operation_id):
        return self.rows.get(operation_id)

    async def mark_candidate_operation_verified(self, operation_id):
        row = self.rows.get(operation_id)
        if row is None:
            return None
        row["verification_succeeded"] = True
        return 120

    async def redeem_candidate_operation(self, operation_id, user_id, provider):
        row = self.rows.get(operation_id)
        if row is None or row["user_id"] != user_id or row["provider"] != provider:
            return None
        del self.rows[operation_id]
        return row


class CandidateRow(dict):
    __getattr__ = dict.__getitem__


AUTH = [{"id": "cred_x", "integrationID": "nan", "label": "API key",
         "active": True, "value": {"type": "key", "key": "synthetic-sentinel"}}]
CONFIG = {"providers": {"nan": {"npm": "@ai-sdk/openai-compatible",
                                   "options": {"baseURL": "https://example.invalid"}}}}


def test_candidate_auth_array_survives_encrypted_read_and_exact_ordered_proof():
    async def run():
        repo = CandidateRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        operation = await service.create_candidate_operation("u", "opencode", CONFIG, AUTH,
                                                              purpose="verification")
        await service.mark_candidate_operation_verified(operation)
        payload = await service.read_candidate_operation(operation, "u", "opencode")
        assert payload["auth"] == AUTH
        assert await service.redeem_candidate_verification(operation, "u", "opencode", CONFIG, AUTH)

    asyncio.run(run())


def test_candidate_legacy_format_requires_reverification():
    async def run():
        repo = CandidateRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        operation = await service.create_candidate_operation("u", "opencode", CONFIG, AUTH)
        row = repo.rows[operation]
        decoded = json.loads(service._fernet().decrypt(row["payload_ciphertext"].encode()))
        decoded.pop("format")
        row["payload_ciphertext"] = service._fernet().encrypt(json.dumps(decoded).encode()).decode()
        with pytest.raises(ValidationFailedError) as error:
            await service.read_candidate_operation(operation, "u", "opencode")
        assert error.value.message_key == "errors.provider.reverification_required"

    asyncio.run(run())


def test_candidate_proof_rejects_auth_array_with_reordered_entries():
    async def run():
        repo = CandidateRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        auth = AUTH + [{**AUTH[0], "id": "cred_y"}]
        operation = await service.create_candidate_operation("u", "opencode", CONFIG, auth,
                                                              purpose="verification")
        await service.mark_candidate_operation_verified(operation)
        assert not await service.redeem_candidate_verification(
            operation, "u", "opencode", CONFIG, list(reversed(auth)))

    asyncio.run(run())


def test_edit_cannot_keep_any_file_from_unconverted_v1_row():
    async def run():
        class LegacyRow(dict):
            __getattr__ = dict.__getitem__

        row = LegacyRow(id="legacy-id", user_id="u", provider="opencode", visibility="personal",
                        group_id=None, format="v1", config_ciphertext="old-ciphertext",
                        auth_ciphertext=None, verification_status="unverified",
                        display_name="Legacy fixture", updated_at=None)

        class Repository:
            async def by_id(self, config_id):
                return row if config_id == row.id else None

            async def name_taken(self, *args, **kwargs):
                return False

        repo = Repository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        with pytest.raises(ValidationFailedError) as error:
            await service.scoped_save(SimpleNamespace(id="u", role="builder"), "opencode",
                                      None, None, "personal", None, display_name="Legacy fixture",
                                      config_id=row.id)
        assert error.value.message_key == "errors.provider.conversion_required"

    asyncio.run(run())


def test_config_upload_requires_root_object_with_providers_without_raising_raw_type_errors():
    with pytest.raises(ValueError, match="object"):
        ProviderConfigService._validate_config_file(b'["not", "an", "object"]')
