"""Docker integration coverage; execute inside the worker container."""
import hashlib
import os
import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker


def test_named_volume_script_output_is_visible_and_recorded():
    task_id = os.getenv("KOSMO_DOCKER_TEST_TASK_ID")
    if not task_id:
        pytest.skip("Set KOSMO_DOCKER_TEST_TASK_ID to an existing task id")

    from app.core.db import AsyncSessionLocal
    from app.domain.tasks.models import Artifact
    from sqlalchemy import select
    from worker.activities.sandbox import run_script

    logical_name = "volume-proof.txt"
    node_id = "volume-proof"
    async def exercise():
        result = await run_script({
            "task_id": task_id,
            "node": {"id": node_id, "type": "script", "outputs": [logical_name],
                     "code": "from pathlib import Path; Path('output/volume-proof.txt').write_text('named-volume-ok', encoding='utf-8')"},
            "inputs": {}, "iteration": 0, "attempt": 987654,
        })
        assert result["state"] == "success", result
        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Artifact).where(Artifact.task_id == task_id,
                Artifact.node_id == node_id, Artifact.attempt == 987654, Artifact.logical_name == logical_name))
        return row

    row = asyncio.run(exercise())

    worker_path = Path("/var/lib/kosmo/tasks") / task_id / "artifacts" / node_id / "0-987654" / logical_name
    assert worker_path.read_text(encoding="utf-8") == "named-volume-ok"
    expected_hash = hashlib.sha256(worker_path.read_bytes()).hexdigest()
    assert row is not None
    assert row.sha256 == expected_hash
