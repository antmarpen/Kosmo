import asyncio
import json

import pytest

from app.api.routes import mcp


@pytest.mark.asyncio
async def test_probe_transport_stages_isolated_ids_and_sends_only_opaque_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("KOSMO_TASK_STORAGE_ROOT", str(tmp_path))
    submitted = []

    class Client:
        async def execute_workflow(self, workflow, *, args, **kwargs):
            submitted.append(args[0])
            return {"errors": []}

    class TemporalClient:
        @staticmethod
        async def connect(*args, **kwargs):
            return Client()

    monkeypatch.setattr("temporalio.client.Client", TemporalClient)
    await asyncio.gather(*[
        mcp._validation_probe(f"candidate-{i}".encode(), {"format": "text"}, 1, f"out-{i}")
        for i in range(2)
    ])

    assert len({item["request_id"] for item in submitted}) == 2
    assert all(set(item) == {"request_id"} for item in submitted)
    assert list((tmp_path / "validation-probes").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ConnectionError("worker unavailable"), TimeoutError("probe timeout")])
async def test_probe_transport_propagates_infrastructure_failure_and_cleans_files(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("KOSMO_TASK_STORAGE_ROOT", str(tmp_path))

    class Client:
        async def execute_workflow(self, *args, **kwargs):
            raise failure

    class TemporalClient:
        @staticmethod
        async def connect(*args, **kwargs):
            return Client()

    monkeypatch.setattr("temporalio.client.Client", TemporalClient)
    with pytest.raises(type(failure)):
        await mcp._validation_probe(b"candidate", {"format": "text"}, 1, "out")
    assert list((tmp_path / "validation-probes").iterdir()) == []
