import json

import pytest

from scripts.migrate_provider_runtime_v2 import convert_files


def test_conversion_adds_providers_and_maps_v1_api_auth():
    config, auth = convert_files(
        b'{"provider":{"nan":{"options":{}}},"model":"nan/model"}',
        b'{"nan":{"type":"api","key":"separate"}}', "row-1",
    )

    assert json.loads(config) == {"providers": {"nan": {"options": {}}}, "model": "nan/model"}
    entries = json.loads(auth)
    assert len(entries) == 1
    assert entries[0]["integrationID"] == "nan"
    assert entries[0]["label"] == "API key"
    assert entries[0]["active"] is True
    assert entries[0]["value"] == {"type": "key", "key": "separate"}
    assert entries[0]["id"].startswith("cred_")


@pytest.mark.parametrize("config,auth", [
    (b'{"provider":{"unknown":true}}', None),
    (b'{"provider":{"nan":{"options":{"apiKey":"inline"}}}', b'{"nan":{"type":"oauth","key":"secret"}}'),
    (b'{"provider":{"nan":{"options":{"apiKey":"inline"}}},"extra":true}', None),
])
def test_unsupported_v1_rows_are_rejected_without_echoing_data(config, auth):
    secret = b"inline"
    with pytest.raises(ValueError) as error:
        convert_files(config, auth, "row-1")
    assert secret.decode() not in str(error.value)


def test_conflicting_inline_and_separate_keys_are_rejected():
    with pytest.raises(ValueError):
        convert_files(b'{"provider":{"nan":{"options":{"apiKey":"inline"}}}}',
                      b'{"nan":{"type":"api","key":"separate"}}', "row-1")
