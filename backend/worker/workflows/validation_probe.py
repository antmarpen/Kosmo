"""One-shot worker-side validation probe; only an opaque staged-file ID enters history."""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class ValidationProbeWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> Any:
        return await workflow.execute_activity(
            "validate_staged_candidate", payload,
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
