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
            {"type": "start", "id": "start", "input_form": [{"name": "topic", "type": "string", "required": True, "label_message_key": "workflow.topic.label"}]},
            {"type": "script", "id": "collect", "inputs": ["topic"], "outputs": ["report.md", "data.json"], "code": "from pathlib import Path\nimport json\nimport os\n\ntopic = os.environ['KOSMO_INPUT_TOPIC']\noutput = Path('output')\noutput.mkdir(exist_ok=True)\n(output / 'report.md').write_text(f'# Security analysis\\n\\nTopic: {topic}\\n\\n## Findings\\n- Review the supplied topic.\\n', encoding='utf-8')\n(output / 'data.json').write_text(json.dumps({'topic': topic, 'findings': []}), encoding='utf-8')"},
            {"type": "ai", "id": "summarize", "agent": {"runtime": "opencode", "model": "default", "instructions": "Summarize the report accurately; do not invent findings."}, "prompt_template": "Read report.md and write a concise security summary to summary.md with Overview, Findings, and Recommendations sections.", "inputs": ["report.md"], "outputs": ["summary.md"], "max_validation_cycles": 3, "validation": {"levels": [
                {"name": "exists_and_parseable", "message_key": "workflow.validation.exists_parseable", "params_schema": {"artifact": "summary.md", "format": "markdown"}},
                {"name": "required_sections", "message_key": "workflow.validation.required_sections", "params_schema": {"sections": ["Overview", "Findings", "Recommendations"], "heading_levels": [1, 2]}},
                {"name": "content_rule", "message_key": "workflow.validation.content_rule", "params_schema": {"rule": "Summary claims must be supported by report.md.", "rule_type": "supported_claims", "input_artifact": "report.md"}},
            ]}},
            {"type": "end", "id": "end"},
        ], "edges": [{"from": "start", "to": "collect"}, {"from": "collect", "to": "summarize"}, {"from": "summarize", "to": "end"}],
    })


async def seed_reference_workflow(db) -> None:
    await ensure_reference_workflow(WorkflowRepository(db))


async def ensure_reference_workflow(repository) -> None:
    if await repository.get_by_name("reference-security-analysis") is None:
        await WorkflowService(repository).publish(reference_workflow_definition())


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
