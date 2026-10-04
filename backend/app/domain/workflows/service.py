import logging
import os
import shutil
from pathlib import Path

from app.domain.workflows.validation import validate_workflow
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError
from shared.errors import ConflictError, ErrorDetail, NotFoundError, PermissionDeniedError, ValidationFailedError
from shared.graph.schema import AiNode, WorkflowDefinition, WorkflowNode
from shared.graph.output_contract import normalize_validation_contracts

logger = logging.getLogger(__name__)


class WorkflowService:
    def __init__(self, repository):
        self.repository = repository

    async def _workflow_reference_check(self, definition):
        """Bounded existence resolver for Workflow-node references.

        Pre-fetches only the referenced workflow ids and returns a synchronous
        resolver for validate_workflow, which stays free of ORM and service
        imports. Returns None when the definition references no sub-workflow.
        """
        referenced = {node.workflow_id for node in definition.nodes if isinstance(node, WorkflowNode)}
        if not referenced:
            return None
        exists: set[str] = set()
        contracts: dict[str, tuple[list[str], list[str]]] = {}
        pending = list(referenced)
        seen = set()
        while pending and len(seen) < 64:
            workflow_id = pending.pop()
            if workflow_id in seen:
                continue
            seen.add(workflow_id)
            if await self.repository.get_workflow(workflow_id) is None:
                continue
            exists.add(workflow_id)
            active = await self.repository.get_active_version(workflow_id)
            if active is None:
                continue
            child = WorkflowDefinition.model_validate(_value(active, "definition"))
            starts = [node for node in child.nodes if getattr(node, "type", None) == "start"]
            inputs = [field.name for field in starts[0].input_form] if len(starts) == 1 else []
            outputs = []
            by_id = {node.id: node for node in child.nodes}
            for edge in child.edges:
                source = by_id.get(edge.from_node)
                if edge.to in {node.id for node in child.nodes if getattr(node, "type", None) == "end"}:
                    outputs.extend(getattr(source, "outputs", []) if source is not None else [])
            contracts[workflow_id] = (inputs, list(dict.fromkeys(outputs)))
            pending.extend(node.workflow_id for node in child.nodes if isinstance(node, WorkflowNode) and node.workflow_id not in seen)
        return (lambda workflow_id: workflow_id in exists,
                lambda workflow_id: contracts.get(workflow_id))

    async def _validate_definition(self, definition):
        self._require_ai_agent_references(definition)
        resolvers = await self._workflow_reference_check(definition)
        if resolvers is None:
            validate_workflow(definition)
        else:
            validate_workflow(definition, workflow_exists=resolvers[0], workflow_contract=resolvers[1])

    @staticmethod
    def _require_ai_agent_references(definition):
        missing = [node.id for node in definition.nodes if isinstance(node, AiNode) and node.agent_id is None]
        if missing:
            raise ValidationFailedError(
                "errors.workflow.invalid",
                details=[ErrorDetail("errors.workflow.agent_reference_required", {"node_id": node_id}) for node_id in missing],
            )

    async def publish(self, definition, published_by=None):
        """Bootstrap helper: create a workflow and publish its first version.

        Only system bootstrap (the seed script) uses this. The HTTP API never
        exposes it: creating is done by create_workflow, and an existing
        workflow publishes through publish_draft so the publication lock,
        revision precondition, and confirmation semantics always apply.
        """
        await self._validate_definition(definition)
        definition = _normalized_definition(definition)
        if await self.repository.find_name_conflict(definition.name) is not None:
            raise ConflictError("errors.workflow.name_conflict", {"name": definition.name})
        workflow = await self.repository.create_workflow(definition.name)
        workflow_id = _value(workflow, "id")
        version = await self.repository.next_version(workflow_id)
        row = await self.repository.create_version(workflow_id, version, definition.model_dump(mode="json", by_alias=True), published_by)
        if hasattr(self.repository, "increment_publication_revision"):
            await self.repository.increment_publication_revision(workflow)
        return {"id": _value(row, "id"), "workflow_id": workflow_id, "version": version, "definition": definition.model_dump(mode="json", by_alias=True)}

    async def create_workflow(self, name, author_id):
        """Create a workflow with an empty initial draft for its author.

        Creation never publishes: the first version appears only through the
        draft-publish path. Names are required and case-insensitively unique.
        """
        cleaned = name.strip()
        if not cleaned:
            raise ValidationFailedError("errors.workflow.name_required")
        if await self.repository.find_name_conflict(cleaned) is not None:
            raise ConflictError("errors.workflow.name_conflict", {"name": cleaned})
        workflow = await self.repository.create_workflow(cleaned)
        workflow_id = _value(workflow, "id")
        draft = await self.repository.create_draft(workflow_id, author_id, None, {}, {})
        return {**self._workflow_view(workflow, None, 1),
                "draft_id": _value(draft, "id"), "draft_revision": _value(draft, "revision")}

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
            raw_definition, repairs = normalize_validation_contracts(_value(draft, "definition"))
            if repairs:
                raise ValidationFailedError("errors.workflow.invalid", details=[ErrorDetail(item["key"], {"path": item["path"]}) for item in repairs])
            definition = WorkflowDefinition.model_validate(raw_definition)
            await self._validate_definition(definition)
        except ValidationError as error:
            raise ValidationFailedError("errors.workflow.invalid_definition") from error
        except ValueError as error:
            if str(error) == "errors.graph.output_validation_conflict":
                raise ValidationFailedError(str(error)) from error
            raise
        # The published definition carries the workflow name: renaming in the
        # editor renames the workflow itself. The name is normalized exactly
        # like creation (blank names are rejected by validate_workflow above),
        # case-insensitive uniqueness still applies, and the rename is part of
        # the locked publication transaction.
        definition = _normalized_definition(definition)
        if definition.name != _value(workflow, "name"):
            conflict = await self.repository.find_name_conflict(definition.name, exclude_workflow_id=workflow_id)
            if conflict is not None:
                raise ConflictError("errors.workflow.name_conflict", {"name": definition.name})
            await self.repository.rename_workflow(workflow_id, definition.name)
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

    async def list_published_versions(self, workflow_id, limit, offset=0):
        """Offset-paginated metadata for published versions, newest first.

        Feeds the activation picker so a previously published inactive
        version stays selectable after a reload; pages small enough for the
        picker keep the listing bounded, and "load more" walks the offset.
        Read-only; activation itself remains an explicit, separate step.
        """
        if await self.repository.get_workflow(workflow_id) is None:
            raise NotFoundError("errors.workflow.not_found")
        active = await self.repository.get_active_version(workflow_id)
        active_id = _value(active, "id") if active is not None else None
        return [{"id": _value(version, "id"), "version": _value(version, "version"),
                 "published_at": _value(version, "created_at"),
                 "is_active": _value(version, "id") == active_id}
                for version in await self.repository.list_versions(workflow_id, limit, offset)]

    async def list_workflows(self, author_id):
        """List view with the caller's own draft count and the workflow task counts.

        Drafts are author-private everywhere else, so the reported draft count
        covers only drafts owned by `author_id`; the repository resolves draft
        and task counts in grouped queries instead of one query per workflow.
        """
        draft_counts = await self.repository.count_drafts_by_author(author_id)
        task_counts = await self.repository.count_tasks_by_workflow()
        result = []
        for workflow in await self.repository.list_workflows():
            workflow_id = _value(workflow, "id")
            active = await self.repository.get_active_version(workflow_id)
            total, active_tasks = task_counts.get(workflow_id, (0, 0))
            result.append(self._workflow_view(workflow, active, draft_counts.get(workflow_id, 0),
                                              total, active_tasks))
        return result

    async def get_workflow(self, workflow_id):
        workflow = await self.repository.get_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError("errors.workflow.not_found")
        total, active_tasks = await self.repository.task_counts(workflow_id)
        return self._workflow_view(workflow, await self.repository.get_active_version(workflow_id),
                                   task_count=total, in_progress_task_count=active_tasks)

    async def delete_workflow(self, workflow_id, delete_tasks: bool):
        """Delete a workflow, optionally with its tasks.

        One transaction: locks the workflow row, blocks while any task is in
        progress, and (when requested) deletes the workflow's tasks before the
        workflow itself. Task storage is removed after commit, best-effort and
        idempotently.
        """
        workflow = await self.repository.lock_workflow(workflow_id)
        if workflow is None:
            raise NotFoundError("errors.workflow.not_found")
        total, in_progress = await self.repository.task_counts(workflow_id)
        if in_progress:
            raise ConflictError("errors.workflow.delete_in_progress", {"count": in_progress})
        if total and not delete_tasks:
            raise ConflictError("errors.workflow.delete_tasks_exist", {"count": total})
        task_ids = await self.repository.list_task_ids(workflow_id) if delete_tasks else []
        if task_ids:
            await self.repository.delete_tasks(workflow_id)
        await self.repository.delete_workflow(workflow_id)
        await self.repository.db.commit()
        _remove_task_storage(task_ids)
        return {"deleted_tasks": len(task_ids)}

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
        canonical, _ = normalize_validation_contracts(definition)
        saved = await self.repository.save_draft(draft_id, author_id, expected_revision, canonical, layout)
        if saved is None:
            raise NotFoundError("errors.workflow.draft_not_found")
        return saved

    async def validate_draft(self, workflow_id, draft_id, user):
        draft = await self.get_draft(workflow_id, draft_id, user)
        try:
            raw_definition, repairs = normalize_validation_contracts(_value(draft, "definition"))
            if repairs:
                return [ErrorDetail(item["key"], {"path": item["path"]}).__dict__ for item in repairs]
            definition = WorkflowDefinition.model_validate(raw_definition)
            await self._validate_definition(definition)
        except ValidationFailedError as error:
            return [detail.__dict__ for detail in error.details]
        except ValidationError as error:
            return [{"message_key": "errors.workflow.invalid_definition", "params": {"field": ".".join(map(str, item["loc"])), "type": item["type"]}} for item in error.errors()]
        except ValueError as error:
            if str(error) == "errors.graph.output_validation_conflict":
                return [{"message_key": str(error), "params": {}}]
            raise
        return []

    @staticmethod
    def _workflow_view(workflow, active, draft_count=0, task_count=0, in_progress_task_count=0):
        return {"id": _value(workflow, "id"), "name": _value(workflow, "name"),
                "publication_revision": _value(workflow, "publication_revision"),
                "active_version": None if active is None else {"id": _value(active, "id"), "version": _value(active, "version"), "definition": _value(active, "definition")},
                "draft_count": draft_count, "task_count": task_count,
                "in_progress_task_count": in_progress_task_count}


def _value(row, key):
    return row[key] if isinstance(row, dict) else getattr(row, key)


def _normalized_definition(definition: WorkflowDefinition) -> WorkflowDefinition:
    """Trim the definition name exactly like creation does.

    Creation strips the entered name before storing it, so publication must
    never reintroduce surrounding whitespace through a rename; the trimmed
    name is what both the workflow row and the published version carry.
    """
    return definition.model_copy(update={"name": definition.name.strip()})


def _remove_task_storage(task_ids):
    """Best-effort, idempotent removal of the deleted tasks' storage directories.

    Only immediate children of the resolved task-storage root are removed so a
    malformed id can never escape the root.
    """
    if not task_ids:
        return
    root = Path(os.getenv("KOSMO_TASK_STORAGE_ROOT", "/var/lib/kosmo/tasks")).resolve()
    for task_id in task_ids:
        try:
            target = (root / task_id).resolve()
            if target.parent != root:
                logger.warning("Skipping unsafe task storage path for %s", task_id)
                continue
            shutil.rmtree(target, ignore_errors=True)
        except OSError:
            logger.warning("Could not remove task storage for %s", task_id)
