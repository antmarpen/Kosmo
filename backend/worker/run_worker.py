import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from worker.activities.tasks import begin_node, completed_nodes, execute_opaque_node, finish_node, finish_task, ordered_nodes, run_node, start_task
from worker.activities.capacity import acquire_agent, admit_queued, cancel_agent_wait, release_agent
from worker.activities.checkpoint import load_checkpoint, publish_completion, reconcile_checkpoint
from worker.activities.ai_node import run_ai_node
from worker.activities.validation import validate_staged_candidate, validate_start_inputs, validate_persisted_start_inputs
from worker.activities.input import record_answer, pending_answer, mark_answer_delivered, await_human_answer
from worker.activities.provider_verify import (
    list_opencode_candidate_models,
    list_opencode_models,
    verify_opencode_candidate_model,
    verify_opencode_model,
)
from worker.workflows.provider_probe import ProviderProbeWorkflow
from worker.workflows.validation_probe import ValidationProbeWorkflow
from worker.workflows.task_workflow import TaskWorkflow


async def main():
    from app.core.config import settings
    from app.core.logging import configure_logging

    configure_logging()
    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    worker = Worker(client, task_queue=settings.temporal_task_queue, workflows=[TaskWorkflow, ProviderProbeWorkflow, ValidationProbeWorkflow],
                    activities=[start_task, completed_nodes, ordered_nodes, begin_node, run_node, run_ai_node, finish_node, finish_task,
                                load_checkpoint, publish_completion, reconcile_checkpoint,
                                  acquire_agent, release_agent, cancel_agent_wait, admit_queued, record_answer,
                                  pending_answer, mark_answer_delivered, await_human_answer,
                                  list_opencode_models, list_opencode_candidate_models,
                                   verify_opencode_model, verify_opencode_candidate_model, validate_staged_candidate,
                                  validate_start_inputs, validate_persisted_start_inputs, execute_opaque_node])
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
