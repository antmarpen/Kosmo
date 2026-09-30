from app.domain.workflows.validation import validate_workflow
from shared.errors import NotFoundError


class WorkflowService:
    def __init__(self, repository):
        self.repository = repository

    async def publish(self, definition):
        validate_workflow(definition)
        workflow = await self.repository.get_by_name(definition.name)
        if workflow is None:
            workflow = await self.repository.create_workflow(definition.name)
        workflow_id = _value(workflow, "id")
        version = await self.repository.next_version(workflow_id)
        row = await self.repository.create_version(workflow_id, version, definition.model_dump(mode="json", by_alias=True))
        await self.repository.activate(workflow_id, _value(row, "id"))
        return {"id": _value(row, "id"), "workflow_id": workflow_id, "version": version, "definition": definition.model_dump(mode="json", by_alias=True)}

    async def list_workflows(self):
        result = []
        for workflow in await self.repository.list_workflows():
            active = await self.repository.get_active_version(_value(workflow, "id"))
            result.append(self._workflow_view(workflow, active))
        return result

    async def get_workflow(self, workflow_id):
        workflow = await self.repository.get_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError("errors.workflow.not_found")
        return self._workflow_view(workflow, await self.repository.get_active_version(workflow_id))

    @staticmethod
    def _workflow_view(workflow, active):
        return {"id": _value(workflow, "id"), "name": _value(workflow, "name"), "active_version": None if active is None else {"id": _value(active, "id"), "version": _value(active, "version"), "definition": _value(active, "definition")}}


def _value(row, key):
    return row[key] if isinstance(row, dict) else getattr(row, key)
