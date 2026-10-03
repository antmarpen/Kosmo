import asyncio

from sqlalchemy import select

from app.core.db import AsyncSessionLocal
from app.core.security import hash_password
from app.domain.identity.models import User, UserRole
from app.domain.workflows.repository import WorkflowRepository
from app.domain.workflows.service import WorkflowService
from shared.graph.schema import WorkflowDefinition


def reference_workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate({
        "schema_version": "v1", "name": "reference-security-analysis",
        "nodes": [
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True, "validation": {"format": "text"}}]},
            {"type": "script", "id": "collect", "inputs": ["topic"], "outputs": ["report", "data"], "code": "report = f'# Security analysis\\n\\nTopic: {topic}\\n\\n## Findings\\n- Review the supplied topic.\\n'\ndata = {'topic': topic, 'findings': []}\nreturn report, data", "output_validation": {"data": {"format": "json", "json_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["topic", "findings"], "properties": {"topic": {"type": "string"}, "findings": {"type": "array"}}, "additionalProperties": False}}}},
            {"type": "ai", "id": "summarize", "agent": {"runtime": "opencode", "model": "default", "instructions": "Summarize the report accurately; do not invent findings."}, "prompt_template": "Read report and write a concise security summary to summary.md.", "inputs": ["report", "data"], "outputs": ["summary.md"], "max_validation_cycles": 3, "output_validation": {"summary.md": {"format": "markdown"}}},
            {"type": "end", "id": "end", "inputs": ["summary.md"]},
        ], "edges": [{"from": "start", "to": "collect"}, {"from": "collect", "to": "summarize"}, {"from": "summarize", "to": "end"}],
    })


async def seed_reference_workflow(db) -> None:
    await ensure_reference_workflow(WorkflowRepository(db))


async def ensure_reference_workflow(repository) -> None:
    workflow = await repository.get_by_name("reference-security-analysis")
    if workflow is None:
        published = await WorkflowService(repository).publish(reference_workflow_definition())
        await repository.activate(published["workflow_id"], published["id"])
        return
    workflow_id = workflow["id"] if isinstance(workflow, dict) else workflow.id
    if await repository.get_active_version(workflow_id) is None:
        version = await repository.get_latest_version(workflow_id)
        if version is not None:
            await repository.activate(workflow_id, version["id"] if isinstance(version, dict) else version.id)


async def upgrade_reference_workflow(repository):
    """Explicitly publish the corrected reference definition without activating it."""
    service = WorkflowService(repository)
    definition = reference_workflow_definition()
    await service._validate_definition(definition)
    workflow = await repository.get_by_name(definition.name)
    if workflow is None:
        raise ValueError("Reference workflow does not exist; use ordinary seeding first")
    workflow_id = workflow["id"] if isinstance(workflow, dict) else workflow.id
    version = await repository.next_version(workflow_id)
    graph = definition.model_dump(mode="json", by_alias=True, exclude_none=True)
    row = await repository.create_version(workflow_id, version, graph)
    await repository.increment_publication_revision(workflow)
    return row


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        for username, password, role in (("admin", "admin-change-me", UserRole.admin), ("test-runner", "runner-change-me", UserRole.runner)):
            user = await db.scalar(select(User).where(User.username == username))
            if user is None:
                db.add(User(username=username, password_hash=hash_password(password), role=role))
        await seed_reference_workflow(db)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
