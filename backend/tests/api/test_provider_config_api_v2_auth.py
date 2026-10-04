import asyncio
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.api.routes.provider_configs import _json_auth_array
from app.domain.provider_configs.service import ProviderConfigService
from shared.errors import ValidationFailedError


def test_auth_parser_preserves_wp19_array_shape_and_rejects_object_without_echo():
    credentials = [{"id":"cred_x","integrationID":"nan","label":"API key","active":True,
                   "value":{"type":"api","key":"synthetic-api-secret"}}]
    assert _json_auth_array(json.dumps(credentials).encode(), "auth.json") == credentials
    with pytest.raises(ValidationFailedError) as error:
        _json_auth_array(b'{"nan":{"type":"api","key":"synthetic-api-secret"}}', "auth.json")
    assert error.value.message_key == "errors.provider.json_array_required"
    assert "synthetic-api-secret" not in str(error.value)


def test_runtime_read_rejects_v1_row_with_keyed_reverification_error():
    service = ProviderConfigService(object(), Fernet.generate_key().decode())
    row = SimpleNamespace(format="v1", config_ciphertext="not-read", auth_ciphertext=None)
    with pytest.raises(ValidationFailedError) as error:
        service.read_row_files(row)
    assert error.value.message_key == "errors.provider.reverification_required"


def test_metadata_contract_only_reports_format_presence_and_verification_status():
    from app.domain.provider_configs.service import ProviderConfigService

    row = SimpleNamespace(id="id-1", provider="opencode", updated_at=None,
                          auth_ciphertext="encrypted", config_ciphertext="encrypted",
                          format="v2", display_name="Provider", verification_status="unverified")
    metadata = ProviderConfigService._metadata(row)
    assert metadata["format"] == "v2"
    assert metadata["auth_present"] is True
    assert metadata["verification_status"] == "unverified"
    assert "ciphertext" not in metadata
    assert "opencode.json" not in metadata
