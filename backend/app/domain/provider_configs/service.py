import json

from cryptography.fernet import Fernet, InvalidToken
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError


class ProviderConfigUnavailable(Exception):
    """Encryption is not configured or stored ciphertext cannot be decrypted."""


class ProviderConfigService:
    """Encrypt provider files before repository writes; decrypt only on execution.

    Key rotation requires re-encrypting every row while both old and new keys
    are available. The current single-key format does not support transparent
    rotation/key identifiers.
    """

    def __init__(self, repository, encryption_key: str):
        self.repository = repository
        self.encryption_key = encryption_key

    async def replace(self, user_id: str, provider: str, config: bytes, auth: bytes | None,
                      visibility: str = "personal", group_id: str | None = None):
        if visibility not in {"personal", "group", "global"}:
            raise ValueError("Invalid provider configuration visibility")
        if (visibility == "group") != (group_id is not None):
            raise ValueError("Group visibility requires exactly one group")
        self._validate_json(config, "opencode.json")
        if auth is not None:
            self._validate_json(auth, "auth.json")
        fernet = self._fernet()
        config_ciphertext = fernet.encrypt(config).decode("ascii")
        auth_ciphertext = fernet.encrypt(auth).decode("ascii") if auth is not None else None
        row = await self.repository.save(user_id, provider, config_ciphertext, auth_ciphertext,
                                         visibility=visibility, group_id=group_id)
        return self._metadata(row)

    async def resolve_files(self, user_id: str, provider: str, group_ids: list[str]) -> dict[str, bytes] | None:
        rows = await self.repository.candidates(user_id, provider, group_ids)
        personal = [row for row in rows if getattr(row, "visibility", "personal") == "personal"]
        groups = [row for row in rows if getattr(row, "visibility", "personal") == "group"]
        global_rows = [row for row in rows if getattr(row, "visibility", "personal") == "global"]
        if personal:
            selected = personal[0]
        elif groups:
            # Multiple matching group configurations are ambiguous; fail closed.
            if len(groups) > 1:
                raise ConflictError("errors.provider.ambiguous_config")
            selected = groups[0]
        elif global_rows:
            selected = global_rows[0]
        else:
            return None
        fernet = self._fernet()
        try:
            config = fernet.decrypt(selected.config_ciphertext.encode("ascii"))
            auth = fernet.decrypt(selected.auth_ciphertext.encode("ascii")) if selected.auth_ciphertext else None
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise ProviderConfigUnavailable("Provider configuration cannot be decrypted with the configured key") from exc
        return {"opencode.json": config, **({"auth.json": auth} if auth is not None else {})}

    async def metadata(self, user_id: str, provider: str) -> dict:
        row = await self.repository.get(user_id, provider)
        if row is None:
            return {"provider": provider, "configured": False, "config_present": False,
                    "auth_present": False, "updated_at": None}
        return self._metadata(row)

    async def read_files(self, user_id: str, provider: str) -> dict[str, bytes] | None:
        row = await self.repository.get(user_id, provider)
        if row is None:
            return None
        fernet = self._fernet()
        try:
            config = fernet.decrypt(row.config_ciphertext.encode("ascii"))
            auth = fernet.decrypt(row.auth_ciphertext.encode("ascii")) if row.auth_ciphertext else None
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise ProviderConfigUnavailable("Provider configuration cannot be decrypted with the configured key") from exc
        return {"opencode.json": config, **({"auth.json": auth} if auth is not None else {})}

    async def delete(self, user_id: str, provider: str) -> bool:
        return await self.repository.delete(user_id, provider)

    async def scoped_replace(self, actor, provider: str, config: bytes, auth: bytes | None,
                             visibility: str, group_id: str | None):
        role = getattr(getattr(actor, "role", None), "value", getattr(actor, "role", None))
        if role not in {"builder", "admin"}:
            raise PermissionDeniedError("errors.provider.forbidden")
        if visibility == "global" and role != "admin":
            raise PermissionDeniedError("errors.provider.global_admin_only")
        if visibility == "group":
            if not group_id or role != "admin" and not await self.repository.is_member(actor.id, group_id):
                raise PermissionDeniedError("errors.provider.group_forbidden")
        existing = await self.repository.get_scope(actor.id, provider, visibility, group_id)
        if existing is not None and role != "admin" and existing.user_id != actor.id:
            raise PermissionDeniedError("errors.provider.forbidden")
        return await self.replace(existing.user_id if existing else actor.id, provider, config, auth, visibility, group_id)

    async def list_visible(self, user_id: str, provider: str) -> list[dict]:
        group_ids = await self.repository.memberships(user_id)
        rows = await self.repository.visible(user_id, provider, group_ids)
        return [{**self._metadata(row), "id": row.id, "visibility": row.visibility,
                 "group_id": row.group_id, "owner_user_id": row.user_id} for row in rows]

    async def delete_owned(self, actor, config_id: str) -> bool:
        row = await self.repository.by_id(config_id)
        if row is None:
            raise NotFoundError("errors.provider.config_not_found")
        role = getattr(getattr(actor, "role", None), "value", getattr(actor, "role", None))
        if role not in {"builder", "admin"} or role != "admin" and row.user_id != actor.id:
            raise PermissionDeniedError("errors.provider.forbidden")
        return await self.repository.delete_scoped(config_id)

    def _fernet(self) -> Fernet:
        if not self.encryption_key:
            raise ProviderConfigUnavailable("KOSMO_CONFIG_ENCRYPTION_KEY is not configured")
        try:
            return Fernet(self.encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ProviderConfigUnavailable("KOSMO_CONFIG_ENCRYPTION_KEY is invalid") from exc

    @staticmethod
    def _validate_json(data: bytes, filename: str) -> None:
        try:
            parsed = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{filename} must contain valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{filename} must contain a JSON object")

    @staticmethod
    def _metadata(row) -> dict:
        updated = row.updated_at
        return {"provider": row.provider, "configured": True, "config_present": True,
                "auth_present": row.auth_ciphertext is not None,
                "updated_at": updated.isoformat() if updated else None}
