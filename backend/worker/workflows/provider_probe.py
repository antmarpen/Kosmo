"""Generic one-shot workflow that runs a provider activity by name.

The API cannot start activities directly against the running Temporal server
(standalone activities are not supported by this server version), so provider
probes run inside a workflow, which is the project's standard execution path.
"""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class ProviderProbeWorkflow:
    @workflow.run
    async def run(self, activity_name: str, payload: dict[str, Any]) -> Any:
        return await workflow.execute_activity(
            activity_name,
            payload,
            start_to_close_timeout=timedelta(seconds=75),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
