import json

import pytest

from worker.activities import validation


@pytest.mark.asyncio
async def test_probe_reads_only_opaque_reference_and_cleans_staged_request(tmp_path, monkeypatch):
    monkeypatch.setenv("KOSMO_TASK_STORAGE_ROOT", str(tmp_path))
    request_id = "0123456789abcdef0123456789abcdef"
    directory = tmp_path / "validation-probes" / request_id
    directory.mkdir(parents=True)
    (directory / "candidate.bin").write_bytes(b"hello")
    (directory / "request.json").write_text(json.dumps({"contract": {"format": "text"}, "level": 1, "logical_name": "x"}))
    async def validate(content, contract, level, runner):
        assert content == b"hello" and contract == {"format": "text"} and level == 1
        return []
    monkeypatch.setattr(validation, "validate_content", validate)

    result = await validation.validate_staged_candidate({"request_id": request_id})

    assert result == {"errors": []}
    assert not directory.exists()


@pytest.mark.asyncio
async def test_probe_rejects_untrusted_path_reference_and_extra_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("KOSMO_TASK_STORAGE_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        await validation.validate_staged_candidate({"request_id": "../../outside"})
    with pytest.raises(ValueError):
        await validation.validate_staged_candidate({"request_id": "0" * 32, "content": "authored"})
