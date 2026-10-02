import json
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.domain.identity.scope_policy import can_create_global, can_create_group, can_create_personal


class ProviderConfigUnavailable(Exception):
    """Encryption is not configured or stored ciphertext cannot be decrypted."""


CANDIDATE_OPERATION_TTL_SECONDS = 120
MAX_DISPLAY_NAME_LENGTH = 80


def normalize_display_name(name: str) -> str:
    """Normalize a user-entered provider display name.

    The display name is mandatory, user-typed, and never defaulted to the
    provider type: it must be 1..MAX_DISPLAY_NAME_LENGTH characters after
    trimming. Invalid values raise keyed validation errors.
    """
    trimmed = name.strip() if isinstance(name, str) else ""
    if not trimmed:
        raise ValidationFailedError("errors.provider.name_invalid")
    if len(trimmed) > MAX_DISPLAY_NAME_LENGTH:
        raise ValidationFailedError("errors.provider.name_too_long",
                                    params={"max_length": MAX_DISPLAY_NAME_LENGTH})
    return trimmed


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
                      visibility: str = "personal", group_id: str | None = None,
                      verification_status: str = "unverified", *, display_name: str):
        if visibility not in {"personal", "group", "global"}:
            raise ValueError("Invalid provider configuration visibility")
        if (visibility == "group") != (group_id is not None):
            raise ValueError("Group visibility requires exactly one group")
        if verification_status not in {"verified", "unverified"}:
            raise ValueError("Invalid provider configuration verification status")
        display_name = normalize_display_name(display_name)
        self._validate_json(config, "opencode.json")
        if auth is not None:
            self._validate_json(auth, "auth.json")
        fernet = self._fernet()
        config_ciphertext = fernet.encrypt(config).decode("ascii")
        auth_ciphertext = fernet.encrypt(auth).decode("ascii") if auth is not None else None
        row = await self.repository.save(user_id, provider, config_ciphertext, auth_ciphertext,
                                         visibility=visibility, group_id=group_id,
                                         verification_status=verification_status,
                                         display_name=display_name)
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
                             visibility: str, group_id: str | None, verification_id: str | None = None,
                             *, display_name: str):
        role = getattr(getattr(actor, "role", None), "value", getattr(actor, "role", None))
        actor.memberships = {}
        if group_id:
            membership_role = await self.repository.membership_role(actor.id, group_id) if hasattr(self.repository, "membership_role") else None
            if membership_role:
                actor.memberships[group_id] = membership_role
        allowed = ((visibility == "personal" and can_create_personal(actor))
                   or (visibility == "group" and group_id is not None and can_create_group(actor, group_id))
                   or (visibility == "global" and can_create_global(actor)))
        if not allowed:
            if visibility == "global":
                raise PermissionDeniedError("errors.provider.global_admin_only")
            raise PermissionDeniedError("errors.provider.group_forbidden" if visibility == "group" else "errors.provider.forbidden")
        if visibility == "global" and role != "admin":
            raise PermissionDeniedError("errors.provider.global_admin_only")
        existing = await self.repository.get_scope(actor.id, provider, visibility, group_id)
        if existing is not None and role != "admin" and existing.user_id != actor.id:
            raise PermissionDeniedError("errors.provider.forbidden")
        # Redemption happens only after the actor is allowed to save: the
        # candidate verification_id proves that the uploaded configuration is
        # the exact one that passed the real container test.
        verification_status = "unverified"
        if verification_id:
            config_value, auth_value = self._parse_json_objects(config, auth)
            if await self.redeem_candidate_verification(verification_id, actor.id, provider,
                                                        config_value, auth_value):
                verification_status = "verified"
        return await self.replace(existing.user_id if existing else actor.id, provider, config, auth,
                                  visibility, group_id, verification_status=verification_status,
                                  display_name=display_name)

    async def list_visible(self, user_id: str, provider: str) -> list[dict]:
        group_ids = await self.repository.memberships(user_id)
        rows = await self.repository.visible(user_id, provider, group_ids)
        return [{"id": row.id, "name": row.display_name, "provider_type": row.provider,
                 "visibility": row.visibility,
                 "verification_status": getattr(row, "verification_status", "unverified"),
                 "owner_user_id": row.user_id} for row in rows]

    async def set_verification_status(self, config_id: str, status: str) -> None:
        await self.repository.set_verification_status(config_id, status)

    async def delete_owned(self, actor, config_id: str) -> bool:
        row = await self.repository.by_id(config_id)
        if row is None:
            raise NotFoundError("errors.provider.config_not_found")
        role = getattr(getattr(actor, "role", None), "value", getattr(actor, "role", None))
        if role != "admin" and row.user_id != actor.id:
            raise PermissionDeniedError("errors.provider.forbidden")
        return await self.repository.delete_scoped(config_id)

    def _fernet(self) -> Fernet:
        if not self.encryption_key:
            raise ProviderConfigUnavailable("KOSMO_CONFIG_ENCRYPTION_KEY is not configured")
        try:
            return Fernet(self.encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ProviderConfigUnavailable("KOSMO_CONFIG_ENCRYPTION_KEY is invalid") from exc

    async def create_candidate_operation(self, user_id: str, provider: str,
                                         config: dict, auth: dict | None) -> str:
        """Encrypt candidate credentials for one short-lived worker hand-off.

        The returned identifier is the only value that may travel through
        Temporal; plaintext credentials never leave this process boundary.
        """
        fernet = self._fernet()
        payload = json.dumps({"config": config, "auth": auth}).encode("utf-8")
        ciphertext = fernet.encrypt(payload).decode("ascii")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=CANDIDATE_OPERATION_TTL_SECONDS)
        row = await self.repository.create_candidate_operation(user_id, provider, ciphertext, expires_at)
        return row.id

    async def consume_candidate_operation(self, operation_id: str, user_id: str, provider: str) -> dict:
        """Resolve and delete a candidate operation exactly once."""
        row = await self.repository.get_candidate_operation(operation_id)
        if row is None:
            raise NotFoundError("errors.provider.config_not_found")
        if row.expires_at <= datetime.now(timezone.utc):
            await self.repository.delete_candidate_operation(operation_id)
            raise NotFoundError("errors.provider.config_not_found")
        if row.user_id != user_id or row.provider != provider:
            raise PermissionDeniedError("errors.provider.forbidden")
        payload = self._candidate_payload(row)
        deleted = await self.repository.delete_candidate_operation(operation_id)
        if not deleted:
            raise NotFoundError("errors.provider.config_not_found")
        return payload

    async def read_candidate_operation(self, operation_id: str, user_id: str, provider: str) -> dict:
        """Resolve a candidate operation WITHOUT consuming it.

        Model verification uses this so the operation survives the container
        test and can later be redeemed at save time as single-use proof that
        the exact credentials passed; TTL and ownership rules match consumption.
        """
        row = await self.repository.get_candidate_operation(operation_id)
        if row is None or row.expires_at <= datetime.now(timezone.utc):
            raise NotFoundError("errors.provider.config_not_found")
        if row.user_id != user_id or row.provider != provider:
            raise PermissionDeniedError("errors.provider.forbidden")
        return self._candidate_payload(row)

    async def redeem_candidate_verification(self, operation_id: str, user_id: str, provider: str,
                                            config: dict | None, auth: dict | None) -> bool:
        """Redeem a single-use verification proof for an exact configuration.

        The operation must belong to the actor and provider and its stored
        config/auth must equal the uploaded values (compared as parsed JSON
        objects, order-insensitive). The row is deleted whenever this actor
        resolved it — on match and on mismatched reuse — and never touched for
        another actor. Missing or expired operations prove nothing.
        """
        row = await self.repository.get_candidate_operation(operation_id)
        if row is None:
            return False
        if row.user_id != user_id or row.provider != provider:
            return False
        if row.expires_at <= datetime.now(timezone.utc):
            await self.repository.delete_candidate_operation(operation_id)
            return False
        payload = self._candidate_payload(row)
        uploaded = {"config": config if isinstance(config, dict) else None,
                    "auth": auth if isinstance(auth, dict) else None}
        if payload != uploaded:
            await self.repository.delete_candidate_operation(operation_id)
            return False
        await self.repository.delete_candidate_operation(operation_id)
        return True

    def _candidate_payload(self, row) -> dict:
        fernet = self._fernet()
        try:
            payload = json.loads(fernet.decrypt(row.payload_ciphertext.encode("ascii")))
        except (InvalidToken, UnicodeEncodeError, ValueError) as exc:
            raise ProviderConfigUnavailable(
                "Candidate operation payload cannot be decrypted with the configured key") from exc
        if not isinstance(payload, dict):
            raise ProviderConfigUnavailable("Candidate operation payload is malformed")
        config, auth = payload.get("config"), payload.get("auth")
        return {"config": config if isinstance(config, dict) else {},
                "auth": auth if isinstance(auth, dict) else None}

    @staticmethod
    def _parse_json_objects(config: bytes, auth: bytes | None) -> tuple[dict | None, dict | None]:
        try:
            config_value = json.loads(config)
            auth_value = json.loads(auth) if auth is not None else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, None
        return (config_value if isinstance(config_value, dict) else None,
                auth_value if isinstance(auth_value, dict) else None)

    async def purge_expired_candidate_operations(self) -> int:
        return await self.repository.purge_expired_candidate_operations()

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
                "name": row.display_name,
                "updated_at": updated.isoformat() if updated else None,
                "verification_status": getattr(row, "verification_status", "unverified")}
