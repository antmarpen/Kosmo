from app.domain.workflows.validation import validate_workflow
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError
from shared.errors import ConflictError, ErrorDetail, NotFoundError, PermissionDeniedError, ValidationFailedError
from shared.graph.schema import WorkflowDefinition


class WorkflowService:
    def __init__(self, repository):
        self.repository = repository

    async def publish(self, definition, published_by=None):
        validate_workflow(definition)
        workflow = await self.repository.get_by_name(definition.name)
        if workflow is None:
            workflow = await self.repository.create_workflow(definition.name)
        workflow_id = _value(workflow, "id")
        version = await self.repository.next_version(workflow_id)
        row = await self.repository.create_version(workflow_id, version, definition.model_dump(mode="json", by_alias=True), published_by)
        if hasattr(self.repository, "increment_publication_revision"):
            await self.repository.increment_publication_revision(workflow)
        return {"id": _value(row, "id"), "workflow_id": workflow_id, "version": version, "definition": definition.model_dump(mode="json", by_alias=True)}

    async def publish_draft(self, workflow_id, draft_id, user, expected_pub_revision, confirm_overwrite=False):
        draft = await self.get_draft(workflow_id, draft_id, user)
        workflow = await self.repository.lock_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError("errors.workflow.not_found")
        revision = _value(workflow, "publication_revision")
        if expected_pub_revision != revision:
            raise ConflictError("errors.workflow.publication_revision_conflict", {"current_revision": revision})
        active = await self.repository.get_active_version(workflow_id)
        published = await self.repository.get_latest_version(workflow_id)
        updated_at = _value(published, "created_at") if published is not None else None
        if published is not None and _value(published, "published_by") != user.id and updated_at and datetime.now(timezone.utc) - updated_at < timedelta(minutes=5) and not confirm_overwrite:
            raise ConflictError("errors.workflow.publication_confirmation_required", {"publication_revision": revision})
        base_id = _value(draft, "base_version_id")
        if active is not None and base_id != _value(active, "id") and not confirm_overwrite:
            raise ConflictError("errors.workflow.stale_base_confirmation_required", {"active_version_id": _value(active, "id")})
        try:
            definition = WorkflowDefinition.model_validate(_value(draft, "definition"))
            validate_workflow(definition)
        except ValidationError as error:
            raise ValidationFailedError("errors.workflow.invalid_definition") from error
        next_version = await self.repository.next_version(workflow_id)
        row = await self.repository.create_version(workflow_id, next_version, definition.model_dump(mode="json", by_alias=True), user.id)
        await self.repository.increment_publication_revision(workflow)
        return {"id": _value(row, "id"), "workflow_id": workflow_id, "version": next_version, "definition": definition.model_dump(mode="json", by_alias=True)}

    async def activate_version(self, workflow_id, version_id, expected_active_revision, confirm_stale_base=False):
        workflow = await self.repository.lock_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError("errors.workflow.not_found")
        active = await self.repository.get_active_version(workflow_id)
        active_revision = _value(active, "version") if active is not None else 0
        if expected_active_revision != active_revision:
            raise ConflictError("errors.workflow.active_revision_conflict", {"current_revision": active_revision})
        version = await self.repository.get_version(version_id)
        if version is None or _value(version, "workflow_id") != workflow_id:
            raise NotFoundError("errors.workflow.version_not_found")
        if active is not None and _value(version, "version") < _value(active, "version") and not confirm_stale_base:
            raise ConflictError("errors.workflow.stale_base_confirmation_required", {"active_version_id": _value(active, "id")})
        await self.repository.activate(workflow_id, version_id)
        return version

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

    async def create_draft(self, workflow_id, author_id):
        if await self.repository.get_workflow(workflow_id) is None:
            raise NotFoundError("errors.workflow.not_found")
        active = await self.repository.get_active_version(workflow_id)
        # Seed from the active version when there is one, otherwise from the
        # latest published version, so a fresh draft reflects the definition the
        # workflow actually has (activation is a separate, optional step).
        base = active or await self.repository.get_latest_version(workflow_id)
        definition = _value(base, "definition") if base else {}
        return await self.repository.create_draft(workflow_id, author_id, _value(base, "id") if base else None,
                                                  definition, {})

    async def list_drafts(self, workflow_id, author_id):
        if await self.repository.get_workflow(workflow_id) is None:
            raise NotFoundError("errors.workflow.not_found")
        return await self.repository.list_drafts(workflow_id, author_id)

    async def get_draft(self, workflow_id, draft_id, user):
        draft = await self.repository.get_draft(workflow_id, draft_id)
        if draft is None:
            raise NotFoundError("errors.workflow.draft_not_found")
        if _value(draft, "author_id") != user.id and user.role.value != "admin":
            raise NotFoundError("errors.workflow.draft_not_found")
        return draft

    async def save_draft(self, workflow_id, draft_id, user, expected_revision, definition, layout):
        draft = await self.get_draft(workflow_id, draft_id, user)
        author_id = _value(draft, "author_id")
        if user.role.value == "admin":
            author_id = user.id if author_id == user.id else author_id
        saved = await self.repository.save_draft(draft_id, author_id, expected_revision, definition, layout)
        if saved is None:
            raise NotFoundError("errors.workflow.draft_not_found")
        return saved

    async def validate_draft(self, workflow_id, draft_id, user):
        draft = await self.get_draft(workflow_id, draft_id, user)
        try:
            definition = WorkflowDefinition.model_validate(_value(draft, "definition"))
            validate_workflow(definition)
        except ValidationFailedError as error:
            return [detail.__dict__ for detail in error.details]
        except ValidationError as error:
            return [{"message_key": "errors.workflow.invalid_definition", "params": {"field": ".".join(map(str, item["loc"])), "type": item["type"]}} for item in error.errors()]
        return []

    @staticmethod
    def _workflow_view(workflow, active):
        return {"id": _value(workflow, "id"), "name": _value(workflow, "name"),
                "publication_revision": _value(workflow, "publication_revision"),
                "active_version": None if active is None else {"id": _value(active, "id"), "version": _value(active, "version"), "definition": _value(active, "definition")}}


def _value(row, key):
    return row[key] if isinstance(row, dict) else getattr(row, key)
