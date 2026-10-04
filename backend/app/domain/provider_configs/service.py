import json
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import IntegrityError
from shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from app.domain.identity.scope_policy import can_create_global, can_create_group, can_create_personal


class ProviderConfigUnavailable(Exception):
    """Encryption is not configured or stored ciphertext cannot be decrypted."""


CANDIDATE_OPERATION_TTL_SECONDS = 120
MAX_DISPLAY_NAME_LENGTH = 80
MAX_PROVIDER_FILE_BYTES = 1_000_000

# The functional unique index backing the case-insensitive display-name rule
# (ProviderConfig.__table_args__; created by migration 0019). Its constraint
# name is the only marker that classifies a commit-time IntegrityError as a
# lost name race, so unrelated database failures are never misclassified.
_NAME_INDEX_CONSTRAINT = "uq_provider_config_owner_provider_name_ci"


def _is_name_index_violation(exc: IntegrityError) -> bool:
    """True only for the case-insensitive display-name unique-index violation.

    The application pre-check resolves ordinary conflicts; the index rejects
    a lost race at commit time. Unrelated database failures never carry this
    constraint name.
    """
    cause = exc.orig if exc.orig is not None else exc
    return _NAME_INDEX_CONSTRAINT in str(cause)


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

    async def create(self, user_id: str, provider: str, config: bytes, auth: bytes | None,
                     visibility: str = "personal", group_id: str | None = None,
                     verification_status: str = "unverified", *, display_name: str):
        """Create a NEW configuration instance (distinct from updating one).

        Every call inserts one row; several instances for the same provider
        may coexist in the same scope. The display name is unique per owner
        and provider case-insensitively: the application pre-check raises the
        keyed conflict error, and the functional unique index is the
        database-level backstop.
        """
        if visibility not in {"personal", "group", "global"}:
            raise ValueError("Invalid provider configuration visibility")
        if (visibility == "group") != (group_id is not None):
            raise ValueError("Group visibility requires exactly one group")
        if verification_status not in {"verified", "unverified"}:
            raise ValueError("Invalid provider configuration verification status")
        display_name = normalize_display_name(display_name)
        self._validate_config_file(config)
        if auth is not None:
            self._validate_auth_file(auth)
        await self._ensure_name_available(user_id, provider, display_name)
        fernet = self._fernet()
        config_ciphertext = fernet.encrypt(config).decode("ascii")
        auth_ciphertext = fernet.encrypt(auth).decode("ascii") if auth is not None else None
        try:
            row = await self.repository.create(user_id, provider, config_ciphertext, auth_ciphertext,
                                               visibility=visibility, group_id=group_id,
                                               verification_status=verification_status,
                                               display_name=display_name)
        except IntegrityError:
            # Lost a race against a concurrent create with the same name: the
            # database index is the authoritative gate.
            raise ConflictError("errors.provider.name_duplicate",
                                params={"name": display_name}) from None
        return self._metadata(row)

    async def _ensure_name_available(self, owner_id: str, provider: str, display_name: str,
                                     *, exclude_id: str | None = None) -> None:
        if await self.repository.name_taken(owner_id, provider, display_name, exclude_id=exclude_id):
            raise ConflictError("errors.provider.name_duplicate", params={"name": display_name})

    async def resolve_files(self, user_id: str, provider: str, group_ids: list[str]) -> dict[str, bytes | str] | None:
        """Resolve the files an agent container will run with.

        Scope precedence stays personal > group > global. Several matching
        instances within one scope resolve by the provisional recency rule
        (see `_most_recent`); the verification and consumption paths target
        instances by id and are unaffected by this fallback.
        """
        rows = await self.repository.candidates(user_id, provider, group_ids)
        personal = [row for row in rows if getattr(row, "visibility", "personal") == "personal"]
        groups = [row for row in rows if getattr(row, "visibility", "personal") == "group"]
        global_rows = [row for row in rows if getattr(row, "visibility", "personal") == "global"]
        selected = next((self._most_recent(scope_rows)
                         for scope_rows in (personal, groups, global_rows) if scope_rows), None)
        if selected is None:
            return None
        self._require_v2_row(selected)
        fernet = self._fernet()
        try:
            config = fernet.decrypt(selected.config_ciphertext.encode("ascii"))
            auth = fernet.decrypt(selected.auth_ciphertext.encode("ascii")) if selected.auth_ciphertext else None
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise ProviderConfigUnavailable("Provider configuration cannot be decrypted with the configured key") from exc
        return {"format": "v2", "opencode.json": config,
                **({"auth.json": auth} if auth is not None else {})}

    @staticmethod
    def _most_recent(rows):
        """Provisional multi-instance resolution rule (approved 2026-10-01).

        When several configurations match the resolved scope, the most
        recently updated one wins, with the row id as a deterministic
        tie-breaker. Recorded as temporary until node-level provider/model
        selection replaces it (docs/specs/ui-refresh-and-provider-instances.md).
        """
        def key(row):
            updated = getattr(row, "updated_at", None) or datetime.min.replace(tzinfo=timezone.utc)
            return (updated, str(getattr(row, "id", "")))
        return max(rows, key=key)

    async def metadata(self, user_id: str, provider: str) -> dict:
        row = await self.repository.get(user_id, provider)
        if row is None:
            return {"provider": provider, "configured": False, "config_present": False,
                    "auth_present": False, "format": None, "updated_at": None,
                    "verification_status": None}
        return self._metadata(row)

    async def read_files(self, user_id: str, provider: str) -> dict[str, bytes | str] | None:
        row = await self.repository.get(user_id, provider)
        if row is None:
            return None
        return self.read_row_files(row)

    async def read_files_by_id(self, config_id: str) -> dict[str, bytes | str] | None:
        """Decrypt exactly one stored configuration by id (worker-side hand-off).

        The id is an opaque reference, never a credential; unknown ids resolve
        to no files at all.
        """
        row = await self.repository.by_id(config_id)
        if row is None:
            return None
        return self.read_row_files(row)

    def read_row_files(self, row) -> dict[str, bytes | str]:
        self._require_v2_row(row)
        return {"format": "v2", **self._decrypt_row_files(row)}

    def _decrypt_row_files(self, row) -> dict[str, bytes]:
        fernet = self._fernet()
        try:
            config = fernet.decrypt(row.config_ciphertext.encode("ascii"))
            auth = fernet.decrypt(row.auth_ciphertext.encode("ascii")) if row.auth_ciphertext else None
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise ProviderConfigUnavailable("Provider configuration cannot be decrypted with the configured key") from exc
        return {"opencode.json": config,
                **({"auth.json": auth} if auth is not None else {})}

    @staticmethod
    def _require_v2_row(row) -> None:
        if getattr(row, "format", "v1") != "v2":
            raise ValidationFailedError("errors.provider.reverification_required")

    @staticmethod
    def _validate_config_file(data: bytes) -> dict:
        parsed = ProviderConfigService._validate_json(data, "opencode.json")
        if "providers" not in parsed or not isinstance(parsed["providers"], dict):
            raise ValueError("opencode.json providers must be an object")
        if "provider" in parsed:
            raise ValueError("Legacy provider configuration requires conversion")
        return parsed

    @staticmethod
    def _validate_auth_file(data: bytes) -> list:
        parsed = ProviderConfigService._validate_json(data, "auth.json")
        if not isinstance(parsed, list):
            raise ValueError("auth.json must contain a credential array")
        for entry in parsed:
            if (not isinstance(entry, dict) or set(entry) != {"id", "integrationID", "label", "active", "value"}
                    or not all(isinstance(entry.get(key), str) and entry[key] for key in ("id", "integrationID", "label"))
                    or not isinstance(entry.get("active"), bool)
                    or not isinstance(entry.get("value"), dict)
                    or set(entry["value"]) != {"type", "key"}
                    or entry["value"].get("type") != "key"
                    or not isinstance(entry["value"].get("key"), str) or not entry["value"]["key"]
                    or not all(isinstance(entry["value"].get(key), str) and entry["value"][key]
                               for key in ("type", "key"))):
                raise ValueError("auth.json contains an unsupported credential entry")
        return parsed

    async def visible_row(self, user_id: str, config_id: str):
        """Resolve one configuration by id under the list visibility model.

        Mirrors `candidates()`: own rows, group rows of groups the caller
        belongs to, and global rows. Unknown ids are not found; existing rows
        outside the caller's visibility are forbidden.
        """
        row = await self.repository.by_id(config_id)
        if row is None:
            raise NotFoundError("errors.provider.config_not_found")
        if row.user_id == user_id or row.visibility == "global" or (
                row.visibility == "group"
                and row.group_id in await self.repository.memberships(user_id)):
            return row
        raise PermissionDeniedError("errors.provider.forbidden")

    async def delete(self, user_id: str, provider: str) -> bool:
        return await self.repository.delete(user_id, provider)

    async def scoped_save(self, actor, provider: str, config: bytes | None, auth: bytes | None,
                          visibility: str, group_id: str | None, verification_id: str | None = None,
                          *, display_name: str, config_id: str | None = None, validate_pair=None):
        """Create a configuration or update one existing instance by id.

        With `config_id` the save targets that exact row (owner or admin);
        rows are never matched or overwritten by scope, so a user can hold
        several named instances per provider. Uploaded files replace the
        stored ones; absent files keep the stored encrypted ones. An update
        that replaces no file requires no proof and keeps the stored
        verification status. `validate_pair` (route-provided) validates the
        configuration that will be stored: the uploaded pair on create, the
        effective pair on update.
        """
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
        if config_id is None:
            return await self._create_with_proof(actor.id, provider, config, auth, visibility, group_id,
                                                 verification_id, display_name=display_name,
                                                 validate_pair=validate_pair)
        return await self._update_by_id(actor, role, config_id, provider, config, auth, visibility,
                                        group_id, verification_id, display_name=display_name,
                                        validate_pair=validate_pair)

    async def _create_with_proof(self, user_id: str, provider: str, config: bytes, auth: bytes | None,
                                 visibility: str, group_id: str | None, verification_id: str | None,
                                 *, display_name: str, validate_pair=None):
        display_name = normalize_display_name(display_name)
        config_value, auth_value = self._validated_pair(config, auth, validate_pair)
        # The name conflict is decided before the proof is redeemed: a
        # rejected save never consumes the single-use verification operation.
        await self._ensure_name_available(user_id, provider, display_name)
        verification_status = "unverified"
        if verification_id:
            # Redemption happens only after the save is otherwise valid: the
            # candidate verification_id proves that the uploaded configuration
            # is the exact one that passed the real container test.
            if await self.redeem_candidate_verification(verification_id, user_id, provider,
                                                        config_value, auth_value):
                verification_status = "verified"
        return await self.create(user_id, provider, config, auth, visibility, group_id,
                                 verification_status=verification_status, display_name=display_name)

    async def _update_by_id(self, actor, role, config_id: str, provider: str,
                            config: bytes | None, auth: bytes | None, visibility: str,
                            group_id: str | None, verification_id: str | None,
                            *, display_name: str, validate_pair=None):
        row = await self.visible_row(actor.id, config_id)
        if role != "admin" and row.user_id != actor.id:
            raise PermissionDeniedError("errors.provider.forbidden")
        if visibility not in {"personal", "group", "global"}:
            raise ValueError("Invalid provider configuration visibility")
        if (visibility == "group") != (group_id is not None):
            raise ValueError("Group visibility requires exactly one group")
        display_name = normalize_display_name(display_name)
        if config is None and auth is None:
            if getattr(row, "format", "v1") != "v2":
                raise ValidationFailedError("errors.provider.conversion_required")
            # No file replaced: keep the stored ciphertext and verification
            # status; a rename or scope move attests nothing new.
            await self._ensure_name_available(row.user_id, provider, display_name, exclude_id=row.id)
            return await self._update_row(
                row, config_ciphertext=row.config_ciphertext, auth_ciphertext=row.auth_ciphertext,
                verification_status=row.verification_status, display_name=display_name,
                visibility=visibility, group_id=group_id)
        # At least one file is replaced: validate the EFFECTIVE pair (the one
        # that will be stored, uploaded files plus kept ones) so a rejected
        # update never overwrites anything, then re-attest it with the proof.
        is_legacy = getattr(row, "format", "v1") != "v2"
        if is_legacy and (config is None or auth is None):
            raise ValidationFailedError("errors.provider.conversion_required")
        stored = self._decrypt_row_files(row)
        effective_config = config if config is not None else stored["opencode.json"]
        effective_auth = auth if auth is not None else stored.get("auth.json")
        config_value, auth_value = self._validated_pair(effective_config, effective_auth, validate_pair)
        # Case-insensitive uniqueness per owner and provider, excluding the
        # row being edited (keeping its own name is never a conflict).
        await self._ensure_name_available(row.user_id, provider, display_name, exclude_id=row.id)
        verification_status = "unverified"
        if verification_id:
            # The proof redemption commits separately from the save below: if
            # the update fails (a lost name race), the row is rolled back
            # unchanged and stays at its stored verification status, so a
            # redeemed proof can never leave the configuration marked
            # verified. The spent proof stays spent (single-use).
            if await self.redeem_candidate_verification(verification_id, actor.id, provider,
                                                        config_value, auth_value):
                verification_status = "verified"
        fernet = self._fernet()
        return await self._update_row(
            row, config_ciphertext=fernet.encrypt(effective_config).decode("ascii"),
            auth_ciphertext=(fernet.encrypt(effective_auth).decode("ascii")
                             if effective_auth is not None else None),
            verification_status=verification_status, display_name=display_name,
            visibility=visibility, group_id=group_id)

    async def _update_row(self, row, *, config_ciphertext: str, auth_ciphertext: str | None,
                          verification_status: str, display_name: str, visibility: str,
                          group_id: str | None) -> dict:
        """Commit the update, translating only a lost name race into the keyed conflict.

        The repository rolls the failed commit back; only the case-insensitive
        name-index violation becomes the localized 409 (matching the create
        path), and any unrelated database failure propagates unchanged.
        """
        try:
            updated = await self.repository.update(
                row, config_ciphertext=config_ciphertext, auth_ciphertext=auth_ciphertext,
                verification_status=verification_status, display_name=display_name,
                visibility=visibility, group_id=group_id)
        except IntegrityError as exc:
            if not _is_name_index_violation(exc):
                raise
            raise ConflictError("errors.provider.name_duplicate",
                                params={"name": display_name}) from None
        return self._metadata(updated)

    def _validated_pair(self, config: bytes, auth: bytes | None, validate_pair):
        """Validate the configuration pair and return its parsed values.

        With a route-provided hook, the keyed JSON/structure errors run there;
        otherwise the service-side JSON checks apply and the pair is parsed
        leniently (a malformed pair simply proves nothing at redemption).
        """
        if validate_pair is not None:
            return validate_pair(config, auth)
        config_value = self._validate_config_file(config)
        if auth is not None:
            auth_value = self._validate_auth_file(auth)
        else:
            auth_value = None
        return config_value, auth_value

    async def list_visible(self, user_id: str, provider: str) -> list[dict]:
        group_ids = await self.repository.memberships(user_id)
        rows = await self.repository.visible(user_id, provider, group_ids)
        return [{"id": row.id, "name": row.display_name, "provider_type": row.provider,
                 "visibility": row.visibility,
                 "verification_status": getattr(row, "verification_status", "unverified"),
                 "owner_user_id": row.user_id,
                 # Metadata only: identifiers and presence flags, never the
                 # stored files or any decrypted value.
                 "group_id": row.group_id,
                 "auth_present": row.auth_ciphertext is not None,
                 "format": getattr(row, "format", "v1")} for row in rows]

    async def set_verification_status(self, config_id: str, status: str,
                                      expected_updated_at=None) -> bool:
        return await self.repository.set_verification_status(
            config_id, status, expected_updated_at=expected_updated_at)

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
                                         config: dict, auth: list | None,
                                         purpose: str = "discovery") -> str:
        """Encrypt candidate credentials for one short-lived worker hand-off.

        The returned identifier is the only value that may travel through
        Temporal; plaintext credentials never leave this process boundary.
        The purpose records what the container run may do: only a
        `verification` operation whose test succeeded can later be redeemed
        as single-use proof.
        """
        if purpose not in {"discovery", "verification"}:
            raise ValueError("Invalid candidate operation purpose")
        fernet = self._fernet()
        self._validate_candidate(config, auth)
        payload = json.dumps({"format": "v2", "config": config, "auth": auth},
                             separators=(",", ":")).encode("utf-8")
        ciphertext = fernet.encrypt(payload).decode("ascii")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=CANDIDATE_OPERATION_TTL_SECONDS)
        row = await self.repository.create_candidate_operation(user_id, provider, ciphertext, expires_at,
                                                               purpose=purpose)
        return row.id

    async def mark_candidate_operation_verified(self, operation_id: str) -> int | None:
        """Record a succeeded container verification on a live operation.

        Returns the seconds of validity left so the client can plan around the
        proof window, or `None` when nothing was marked and no proof exists.
        """
        return await self.repository.mark_candidate_operation_verified(operation_id)

    async def consume_candidate_operation(self, operation_id: str, user_id: str, provider: str) -> dict:
        """Resolve and delete a candidate operation exactly once, atomically.

        The conditional delete is the single-use gate; the follow-up read only
        classifies why a failed claim found nothing for error reporting and
        can never resurrect a consumed operation.
        """
        claimed = await self.repository.consume_candidate_operation(operation_id, user_id, provider)
        if claimed is not None:
            return self._candidate_payload_ciphertext(claimed["payload_ciphertext"])
        row = await self.repository.get_candidate_operation(operation_id)
        if row is None:
            raise NotFoundError("errors.provider.config_not_found")
        if row.user_id != user_id or row.provider != provider:
            raise PermissionDeniedError("errors.provider.forbidden")
        if row.expires_at <= datetime.now(timezone.utc):
            await self.repository.delete_candidate_operation(operation_id)
        raise NotFoundError("errors.provider.config_not_found")

    async def redeem_candidate_verification(self, operation_id: str, user_id: str, provider: str,
                                             config: dict | None, auth: list | None) -> bool:
        """Redeem a single-use verification proof for an exact configuration.

        Redemption is one atomic conditional delete: it lands only for the
        owner's verification-purpose operation with a recorded successful
        container test and a live TTL, so a concurrent second redemption can
        never double-spend the same proof. The stored config/auth must equal
        the uploaded values (compared as parsed JSON objects,
        order-insensitive); a claimed-but-mismatched payload is consumed
        anyway — a reused operation is untrusted. Missing, foreign, expired,
        discovery-purpose, and failed-verification operations prove nothing.
        """
        claimed = await self.repository.redeem_candidate_operation(operation_id, user_id, provider)
        if claimed is None:
            await self._cleanup_unredeemable(operation_id, user_id)
            return False
        payload = self._candidate_payload_ciphertext(claimed["payload_ciphertext"])
        if payload.get("format") != "v2":
            raise ValidationFailedError("errors.provider.reverification_required")
        uploaded = {"format": "v2", "config": config if isinstance(config, dict) else None,
                    "auth": auth if isinstance(auth, list) else None}
        return payload == uploaded

    async def _cleanup_unredeemable(self, operation_id: str, user_id: str) -> None:
        """Best-effort removal of the caller's own expired operation row.

        Foreign rows are never touched; live rows are left alone (only the
        atomic claim may consume them).
        """
        row = await self.repository.get_candidate_operation(operation_id)
        if row is None or row.user_id != user_id:
            return
        if row.expires_at <= datetime.now(timezone.utc):
            await self.repository.delete_candidate_operation(operation_id)

    def _candidate_payload_ciphertext(self, ciphertext: str) -> dict:
        fernet = self._fernet()
        try:
            payload = json.loads(fernet.decrypt(ciphertext.encode("ascii")))
        except (InvalidToken, UnicodeEncodeError, ValueError) as exc:
            raise ProviderConfigUnavailable(
                "Candidate operation payload cannot be decrypted with the configured key") from exc
        if not isinstance(payload, dict):
            raise ProviderConfigUnavailable("Candidate operation payload is malformed")
        if payload.get("format") != "v2":
            raise ValidationFailedError("errors.provider.reverification_required")
        config, auth = payload.get("config"), payload.get("auth")
        if not isinstance(config, dict) or (auth is not None and not isinstance(auth, list)):
            raise ProviderConfigUnavailable("Candidate operation payload is malformed")
        self._validate_candidate(config, auth)
        return {"format": "v2", "config": config, "auth": auth}

    @staticmethod
    def _validate_candidate(config, auth):
        if (not isinstance(config, dict) or "providers" not in config
                or not isinstance(config["providers"], dict) or "provider" in config):
            raise ValueError("Provider configuration is invalid")
        try:
            encoded = json.dumps(config, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError):
            raise ValueError("Provider configuration is invalid") from None
        if len(encoded) > MAX_PROVIDER_FILE_BYTES:
            raise ValueError("Provider configuration is too large")
        if auth is not None:
            if not isinstance(auth, list):
                raise ValueError("Provider credentials are invalid")
            try:
                encoded_auth = json.dumps(auth, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError, UnicodeEncodeError):
                raise ValueError("Provider credentials are invalid") from None
            if len(encoded_auth) > MAX_PROVIDER_FILE_BYTES:
                raise ValueError("Provider credentials are too large")
            for item in auth:
                if (not isinstance(item, dict) or set(item) != {"id", "integrationID", "label", "active", "value"}
                        or not isinstance(item.get("value"), dict)
                        or set(item["value"]) != {"type", "key"}
                        or item["value"].get("type") != "key"
                        or not all(isinstance(item.get(k), str) and item[k] for k in ("id", "integrationID", "label"))
                        or not isinstance(item.get("active"), bool)
                        or not all(isinstance(item["value"].get(k), str) and item["value"][k] for k in ("type", "key"))):
                    raise ValueError("Provider credentials are invalid")

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
        return self._candidate_payload_ciphertext(row.payload_ciphertext)

    async def purge_expired_candidate_operations(self) -> int:
        return await self.repository.purge_expired_candidate_operations()

    @staticmethod
    def _validate_json(data: bytes, filename: str):
        if len(data) > MAX_PROVIDER_FILE_BYTES:
            raise ValueError("Provider file is too large")
        try:
            parsed = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{filename} must contain valid JSON") from exc
        return parsed

    @staticmethod
    def _metadata(row) -> dict:
        updated = row.updated_at
        return {"id": row.id,
                "provider": row.provider, "configured": True, "config_present": True,
                "auth_present": row.auth_ciphertext is not None,
                "format": getattr(row, "format", "v1"),
                "name": row.display_name,
                "updated_at": updated.isoformat() if updated else None,
                "verification_status": getattr(row, "verification_status", "unverified")}
