import re
from types import SimpleNamespace
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.domain.identity.scope_policy import can_create_global, can_create_group, can_create_personal
from app.domain.mcp_servers.models import McpServer
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_NAME_CONSTRAINTS = {"uq_mcp_servers_personal_name_ci", "uq_mcp_servers_group_name_ci", "uq_mcp_servers_global_name_ci"}


def _fail(key="errors.mcp_server.invalid"):
    raise ValidationFailedError(key)


def _role(actor):
    role = getattr(actor, "role", None)
    return str(getattr(role, "value", role))


def _name(value):
    value = value.strip() if isinstance(value, str) else ""
    if not 1 <= len(value) <= 80:
        _fail("errors.mcp_server.name_invalid")
    if value.casefold() == "kosmo-validator":
        _fail("errors.mcp_server.name_reserved")
    return value


def _entries(transport, old_transport, old_ciphertext, create, allow_keep=True):
    kind = transport.get("type")
    collection = "env" if kind == "stdio" else "headers"
    result, secrets, ciphertext = [], {}, {}
    seen = set()
    old_kind = old_transport.get("type") if old_transport else None
    same_base = old_transport is not None and old_kind == kind
    for item in transport.get(collection, []):
        entry_name, secret, action = item.get("name"), item.get("secret"), item.get("action")
        key = entry_name.casefold() if kind == "http" and isinstance(entry_name, str) else entry_name
        valid_name = (_ENV_NAME.fullmatch(entry_name or "") if kind == "stdio"
                      else _HEADER_NAME.fullmatch(entry_name or ""))
        if not valid_name or key in seen or not isinstance(secret, bool):
            _fail()
        seen.add(key)
        old = next((entry for entry in old_transport.get(collection, []) if
                    (entry["name"].casefold() if kind == "http" else entry["name"]) == key), None) if same_base else None
        if action not in {"replace", "keep", "remove"} or (create and action != "replace"):
            _fail()
        if action in {"keep", "remove"} and old is None:
            _fail()
        if action in {"keep", "remove"} and old["secret"] != secret:
            _fail()
        if old is not None and old["secret"] != secret and action != "replace":
            _fail()
        if action == "remove":
            if "value" in item:
                _fail()
            continue
        if action == "keep":
            if not allow_keep or not old or not old["secret"] or not old.get("is_set") or "value" in item:
                _fail()
            result.append({"name": entry_name, "secret": True, "is_set": True})
            ciphertext[entry_name] = old_ciphertext[old["name"]]
            continue
        if "value" not in item or not isinstance(item["value"], str):
            _fail()
        value = item["value"]
        if kind == "http" and ("\r" in entry_name or "\n" in entry_name or "\r" in value or "\n" in value):
            _fail()
        if secret:
            secrets[entry_name] = value
            result.append({"name": entry_name, "secret": True, "is_set": True})
        else:
            result.append({"name": entry_name, "secret": False, "value": value, "is_set": True})
    return result, secrets, ciphertext


def _prepare(transport, old_transport=None, old_ciphertext=None, create=False, allow_keep=True):
    if not isinstance(transport, dict) or transport.get("type") not in {"stdio", "http"}:
        _fail()
    kind = transport["type"]
    allowed = {"type", "command", "args", "env"} if kind == "stdio" else {"type", "url", "headers"}
    if set(transport) - allowed:
        _fail()
    if kind == "stdio":
        command, args = transport.get("command"), transport.get("args")
        if not isinstance(command, str) or not command.strip() or any(c.isspace() for c in command) or not isinstance(args, list) or not all(isinstance(v, str) for v in args):
            _fail()
        base = {"type": kind, "command": command, "args": args}
    else:
        url = transport.get("url")
        try:
            parsed = urlsplit(url)
            valid_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc) and parsed.username is None and parsed.password is None
        except (TypeError, ValueError):
            valid_url = False
        if not valid_url:
            _fail()
        base = {"type": kind, "url": url}
    entries, secrets, retained_ciphertext = _entries(transport, old_transport, old_ciphertext or {}, create, allow_keep)
    coll = "env" if kind == "stdio" else "headers"
    base[coll] = entries
    return base, secrets, retained_ciphertext


def _safe(row):
    return {"id": row.id, "name": row.name, "owner_user_id": row.owner_user_id,
            "visibility": row.visibility, "group_id": row.group_id,
            "transport": row.safe_config, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


class McpServerService:
    def __init__(self, repository):
        self.repository = repository

    async def _authorize_scope(self, actor, visibility, group_id):
        if visibility not in {"personal", "group", "global"} or ((visibility == "group") != (group_id is not None)):
            _fail("errors.mcp_server.scope_invalid")
        member_role = await self.repository.membership_role(actor.id, group_id) if group_id else None
        scoped = SimpleNamespace(id=actor.id, role=getattr(actor, "role", None),
                                 memberships={group_id: member_role} if member_role else {})
        allowed = ((visibility == "personal" and can_create_personal(scoped)) or
                   (visibility == "group" and can_create_group(scoped, group_id)) or
                   (visibility == "global" and can_create_global(scoped)))
        if not allowed:
            raise PermissionDeniedError("errors.mcp_server.global_admin_only" if visibility == "global" else "errors.mcp_server.scope_forbidden")

    async def create(self, actor, data):
        name = _name(data.get("name"))
        visibility, group_id = data.get("visibility", "personal"), data.get("group_id")
        await self._authorize_scope(actor, visibility, group_id)
        if await self.repository.name_conflict(actor.id, name, visibility, group_id):
            raise ConflictError("errors.mcp_server.name_duplicate")
        safe, secrets, _ = _prepare(data.get("transport"), create=True)
        self._check_encryption_key(secrets)
        row = McpServer(name=name, owner_user_id=actor.id, visibility=visibility, group_id=group_id,
                        transport_type=safe["type"], safe_config=safe, secret_ciphertext={})
        try:
            row = await self.repository.create(row, secret_values=secrets)
        except (RuntimeError, ValueError, TypeError):
            _fail("errors.mcp_server.encryption_unavailable")
        except IntegrityError as exc:
            if self._name_race(exc):
                raise ConflictError("errors.mcp_server.name_duplicate") from None
            raise
        return _safe(row)

    @staticmethod
    def _check_encryption_key(values):
        if not values:
            return
        if not settings.config_encryption_key:
            _fail("errors.mcp_server.encryption_unavailable")
        try:
            Fernet(settings.config_encryption_key.encode())
        except (ValueError, TypeError):
            _fail("errors.mcp_server.encryption_unavailable")

    async def list_visible(self, user_id):
        groups = await self.repository.memberships(user_id)
        rows = await self.repository.visible_candidates(user_id, groups)
        priority = {"personal": 0, "group": 1, "global": 2}
        rows.sort(key=lambda row: (priority[row.visibility], row.name.casefold(), row.id))
        # Lists intentionally omit transport configuration.
        return [{k: v for k, v in _safe(row).items() if k != "transport"} for row in rows]

    async def get_visible(self, user_id, entity_id):
        row = await self.repository.by_id(entity_id)
        if row is None:
            raise NotFoundError("errors.mcp_server.not_found")
        if row.visibility == "personal" and row.owner_user_id == user_id or row.visibility == "global":
            return _safe(row)
        if row.visibility == "group" and row.group_id in await self.repository.memberships(user_id):
            return _safe(row)
        raise PermissionDeniedError("errors.mcp_server.forbidden")

    async def _mutable(self, actor, entity_id):
        row = await self.repository.by_id(entity_id)
        if row is None:
            raise NotFoundError("errors.mcp_server.not_found")
        await self.get_visible(actor.id, entity_id)
        if _role(actor) != "admin" and row.owner_user_id != actor.id:
            raise PermissionDeniedError("errors.mcp_server.forbidden")
        return row

    async def update(self, actor, entity_id, changes):
        row = await self._mutable(actor, entity_id)
        values = dict(changes)
        name = _name(values["name"]) if "name" in values else row.name
        visibility = values.get("visibility", row.visibility)
        group_id = values.get("group_id", row.group_id if visibility == row.visibility else None)
        await self._authorize_scope(actor, visibility, group_id)
        if await self.repository.name_conflict(row.owner_user_id, name, visibility, group_id, exclude_id=row.id):
            raise ConflictError("errors.mcp_server.name_duplicate")
        safe, secrets, retained = _prepare(values.pop("transport"), row.safe_config, row.secret_ciphertext,
                                           allow_keep=name == row.name) if "transport" in values else (row.safe_config, {}, dict(row.secret_ciphertext))
        self._check_encryption_key(secrets)
        values.update(name=name, visibility=visibility, group_id=group_id)
        if "transport" in changes:
            values.update(transport_type=safe["type"], safe_config=safe)
        try:
            updated = await self.repository.update(row, secret_values=secrets, retained_ciphertext=retained, **values)
        except (RuntimeError, ValueError, TypeError):
            _fail("errors.mcp_server.encryption_unavailable")
        except IntegrityError as exc:
            if self._name_race(exc):
                raise ConflictError("errors.mcp_server.name_duplicate") from None
            raise
        return _safe(updated)

    async def delete(self, actor, entity_id):
        await self._mutable(actor, entity_id)
        return await self.repository.delete(entity_id)

    @staticmethod
    def _name_race(exc):
        cause = exc.orig if exc.orig is not None else exc
        return any(name in str(cause) for name in _NAME_CONSTRAINTS)
