import asyncio
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet

from app.domain.provider_configs.service import ProviderConfigService


class ConfigRepository:
    def __init__(self):
        self.rows = []
        self.row = None

    async def save(self, user_id, provider, config_ciphertext, auth_ciphertext,
                   visibility="personal", group_id=None, verification_status="unverified",
                   *, display_name):
        # Mirrors the real repository contract: an existing scoped row is
        # updated in place (including the display name), never duplicated.
        existing = next((r for r in self.rows if r.user_id == user_id and r.provider == provider
                         and r.visibility == visibility and r.group_id == group_id), None)
        if existing is not None:
            existing["config_ciphertext"] = config_ciphertext
            existing["auth_ciphertext"] = auth_ciphertext
            existing["verification_status"] = verification_status
            existing["display_name"] = display_name
            self.row = existing
            return self.row
        self.row = ConfigRow(id=f"config-{len(self.rows) + 1}", user_id=user_id, provider=provider,
                              config_ciphertext=config_ciphertext, auth_ciphertext=auth_ciphertext,
                              visibility=visibility, group_id=group_id, updated_at=None,
                              verification_status=verification_status, display_name=display_name)
        self.rows.append(self.row)
        return self.row

    async def get(self, user_id, provider):
        return next((r for r in self.rows if r.user_id == user_id and r.provider == provider
                     and r.visibility == "personal"), None)

    async def candidates(self, user_id, provider, group_ids):
        return [r for r in self.rows if r.provider == provider and
                ((r.visibility == "personal" and r.user_id == user_id) or r.visibility == "global" or
                 (r.visibility == "group" and r.group_id in group_ids))]

    async def memberships(self, user_id):
        return []

    async def visible(self, user_id, provider, group_ids):
        return await self.candidates(user_id, provider, group_ids)

    async def set_verification_status(self, config_id, status):
        self.row.verification_status = status

    async def delete(self, user_id, provider):
        if await self.get(user_id, provider):
            self.rows.remove(self.row)
            self.row = None
            return True
        return False


class ConfigRow(dict):
    __getattr__ = dict.__getitem__


def test_provider_config_encrypts_files_at_rest_and_roundtrips():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        config = b'{"model":"opencode/big-pickle"}'
        auth = b'{"opencode":{"key":"secret-value"}}'
        await service.replace("user-1", "opencode", config, auth, display_name="Roundtrip Config")

        assert config.decode() not in repo.row["config_ciphertext"]
        assert auth.decode() not in repo.row["auth_ciphertext"]
        assert "secret-value" not in repo.row["auth_ciphertext"]
        assert await service.read_files("user-1", "opencode") == {
            "opencode.json": config, "auth.json": auth,
        }

    asyncio.run(run())


def test_provider_config_metadata_and_delete_never_return_file_contents():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        await service.replace("user-1", "opencode", b'{"model":"m"}', None,
                              display_name="Metadata Config")
        metadata = await service.metadata("user-1", "opencode")

        assert metadata["configured"] is True
        assert metadata["auth_present"] is False
        assert "config_ciphertext" not in metadata
        assert await service.delete("user-1", "opencode") is True
        assert await service.metadata("user-1", "opencode") == {
            "provider": "opencode", "configured": False,
            "config_present": False, "auth_present": False,
            "updated_at": None,
        }

    asyncio.run(run())


def test_provider_config_resolution_prefers_personal_then_group_then_global():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        await service.replace("admin", "opencode", b'{"model":"global"}', None,
                              visibility="global", display_name="Global Config")
        await service.replace("admin", "opencode", b'{"model":"group"}', None,
                              visibility="group", group_id="g1", display_name="Group Config")
        await service.replace("runner", "opencode", b'{"model":"personal"}', None,
                              display_name="Personal Config")
        files = await service.resolve_files("runner", "opencode", ["g1"])
        assert b'personal' in files["opencode.json"]

    asyncio.run(run())


def test_ambiguous_group_provider_configs_raise_structured_conflict():
    from shared.errors import ConflictError

    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        await service.replace("owner-1", "opencode", b'{"model":"group-a"}', None,
                              visibility="group", group_id="g1", display_name="Group A")
        await service.replace("owner-2", "opencode", b'{"model":"group-b"}', None,
                              visibility="group", group_id="g2", display_name="Group B")
        try:
            await service.resolve_files("runner", "opencode", ["g1", "g2"])
        except ConflictError as exc:
            assert exc.message_key == "errors.provider.ambiguous_config"
        else:
            raise AssertionError("Ambiguous group configurations must fail closed")

    asyncio.run(run())


def test_group_then_global_provider_config_resolution():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        await service.replace("group-owner", "opencode", b'{"model":"group"}', None,
                              visibility="group", group_id="team-1", display_name="Group Config")
        await service.replace("admin", "opencode", b'{"model":"global"}', None,
                              visibility="global", display_name="Global Config")
        group_files = await service.resolve_files("member", "opencode", ["team-1"])
        assert b'group' in group_files["opencode.json"]
        global_files = await service.resolve_files("outsider", "opencode", [])
        assert b'global' in global_files["opencode.json"]

    asyncio.run(run())


def test_list_visible_reports_verification_status_without_stored_model_metadata():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        await service.replace("user-1", "opencode", b'{"provider":{"a":{},"b":{}}}', None,
                              display_name="Listed Config")
        metadata = (await service.list_visible("user-1", "opencode"))[0]
        assert metadata["verification_status"] == "unverified"
        # A provider configuration never stores a model: no selected model and
        # no model-derived count may leak into the metadata contract.
        assert "selected_model" not in metadata
        assert "model_count" not in metadata
        assert "ciphertext" not in str(metadata) and "config" not in metadata
        await service.set_verification_status(repo.row.id, "verified")
        assert (await service.list_visible("user-1", "opencode"))[0]["verification_status"] == "verified"
        await service.set_verification_status(repo.row.id, "failed")
        assert (await service.list_visible("user-1", "opencode"))[0]["verification_status"] == "failed"
    asyncio.run(run())


def test_replace_stores_and_returns_the_user_entered_display_name():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        metadata = await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                                         display_name="Team OpenCode Config")

        assert repo.row["display_name"] == "Team OpenCode Config"
        # The save (PUT) response exposes the user-entered name next to the type.
        assert metadata["name"] == "Team OpenCode Config"
        assert metadata["provider"] == "opencode"
        single = await service.metadata("user-1", "opencode")
        assert single["name"] == "Team OpenCode Config"
        listed = (await service.list_visible("user-1", "opencode"))[0]
        # The list keeps the `name` JSON key for the display name while
        # `provider_type` reports the immutable provider type: two different
        # things that must not be conflated.
        assert listed["name"] == "Team OpenCode Config"
        assert listed["provider_type"] == "opencode"

    asyncio.run(run())


def test_display_name_is_mandatory_trimmed_and_bounded():
    from shared.errors import ValidationFailedError

    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())

        for rejected in ("", "   "):
            try:
                await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                                      display_name=rejected)
            except ValidationFailedError as exc:
                assert exc.message_key == "errors.provider.name_invalid"
            else:
                raise AssertionError("Empty or whitespace-only display names must be rejected")
        try:
            await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                                  display_name="x" * 81)
        except ValidationFailedError as exc:
            assert exc.message_key == "errors.provider.name_too_long"
        else:
            raise AssertionError("Display names over 80 characters must be rejected")
        assert repo.rows == []

        await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                              display_name="  Padded Name  ")
        assert repo.row["display_name"] == "Padded Name"
        assert (await service.list_visible("user-1", "opencode"))[0]["name"] == "Padded Name"

    asyncio.run(run())


def test_replacing_a_scoped_config_replaces_the_display_name():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                              display_name="First Name")
        await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                              display_name="Second Name")

        assert len(repo.rows) == 1
        assert repo.row["display_name"] == "Second Name"
        assert (await service.list_visible("user-1", "opencode"))[0]["name"] == "Second Name"

    asyncio.run(run())


def test_replace_records_verification_status_and_rejects_unknown_values():
    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        metadata = await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                                         verification_status="verified", display_name="Verified Config")
        assert metadata["verification_status"] == "verified"
        assert repo.row["verification_status"] == "verified"
        assert "selected_model" not in metadata and "model_count" not in metadata
        try:
            await service.replace("user-1", "opencode", b'{"provider":{}}', None,
                                  verification_status="attested", display_name="Verified Config")
        except ValueError:
            pass
        else:
            raise AssertionError("Unknown verification statuses must be rejected")
    asyncio.run(run())


class CandidateOperationRow(dict):
    __getattr__ = dict.__getitem__


class CandidateOperationRepository(ConfigRepository):
    def __init__(self):
        super().__init__()
        self.candidate_operations = {}

    async def create_candidate_operation(self, user_id, provider, payload_ciphertext, expires_at):
        operation_id = f"op-{len(self.candidate_operations) + 1}"
        self.candidate_operations[operation_id] = CandidateOperationRow(
            id=operation_id, user_id=user_id, provider=provider,
            payload_ciphertext=payload_ciphertext, expires_at=expires_at,
        )
        return self.candidate_operations[operation_id]

    async def get_candidate_operation(self, operation_id):
        return self.candidate_operations.get(operation_id)

    async def delete_candidate_operation(self, operation_id):
        return self.candidate_operations.pop(operation_id, None) is not None

    async def purge_expired_candidate_operations(self):
        now = datetime.now(timezone.utc)
        expired = [key for key, row in self.candidate_operations.items() if row["expires_at"] <= now]
        for key in expired:
            del self.candidate_operations[key]
        return len(expired)


def test_candidate_operation_roundtrip_is_encrypted_short_lived_and_single_use():
    async def run():
        repo = CandidateOperationRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        config = {"provider": {"x": {"options": {"apiKey": "secret-key"}}}}
        auth = {"x": {"key": "auth-secret"}}

        operation_id = await service.create_candidate_operation("user-1", "opencode", config, auth)

        row = repo.candidate_operations[operation_id]
        assert "secret-key" not in row["payload_ciphertext"]
        assert "auth-secret" not in row["payload_ciphertext"]
        remaining = row["expires_at"] - datetime.now(timezone.utc)
        assert timedelta(seconds=0) < remaining <= timedelta(seconds=120)

        resolved = await service.consume_candidate_operation(operation_id, "user-1", "opencode")
        assert resolved == {"config": config, "auth": auth}
        assert operation_id not in repo.candidate_operations

    asyncio.run(run())


def test_candidate_operation_without_auth_roundtrips_none_and_scopes_to_owner():
    async def run():
        from shared.errors import PermissionDeniedError

        repo = CandidateOperationRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        config = {"provider": {"x": {"options": {"apiKey": "secret-key"}}}}

        operation_id = await service.create_candidate_operation("user-1", "opencode", config, None)
        resolved = await service.consume_candidate_operation(operation_id, "user-1", "opencode")
        assert resolved == {"config": config, "auth": None}

        other = await service.create_candidate_operation("user-1", "opencode", config, None)
        try:
            await service.consume_candidate_operation(other, "user-2", "opencode")
        except PermissionDeniedError as exc:
            assert exc.message_key == "errors.provider.forbidden"
        else:
            raise AssertionError("Candidate operations must only be consumable by their owner")
        assert other in repo.candidate_operations

    asyncio.run(run())


def test_missing_or_expired_candidate_operation_reports_not_found_and_cleans_up():
    async def run():
        from shared.errors import NotFoundError

        repo = CandidateOperationRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())

        try:
            await service.consume_candidate_operation("missing", "user-1", "opencode")
        except NotFoundError as exc:
            assert exc.message_key == "errors.provider.config_not_found"
        else:
            raise AssertionError("Missing candidate operations must report not found")

        operation_id = await service.create_candidate_operation(
            "user-1", "opencode", {"provider": {"x": {"options": {"apiKey": "k"}}}}, None)
        repo.candidate_operations[operation_id]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        try:
            await service.consume_candidate_operation(operation_id, "user-1", "opencode")
        except NotFoundError as exc:
            assert exc.message_key == "errors.provider.config_not_found"
        else:
            raise AssertionError("Expired candidate operations must report not found")
        assert operation_id not in repo.candidate_operations

    asyncio.run(run())


def test_purge_expired_candidate_operations_removes_only_expired_rows():
    async def run():
        repo = CandidateOperationRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        live = await service.create_candidate_operation(
            "user-1", "opencode", {"provider": {"x": {"options": {"apiKey": "k"}}}}, None)
        expired = await service.create_candidate_operation(
            "user-2", "opencode", {"provider": {"x": {"options": {"apiKey": "k"}}}}, None)
        repo.candidate_operations[expired]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

        removed = await service.purge_expired_candidate_operations()

        assert removed == 1
        assert expired not in repo.candidate_operations
        assert live in repo.candidate_operations

    asyncio.run(run())


def test_read_candidate_operation_resolves_without_consuming():
    async def run():
        from shared.errors import NotFoundError, PermissionDeniedError

        repo = CandidateOperationRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        config = {"provider": {"x": {"options": {"apiKey": "secret-key"}}}}

        operation_id = await service.create_candidate_operation("user-1", "opencode", config, None)
        first = await service.read_candidate_operation(operation_id, "user-1", "opencode")
        second = await service.read_candidate_operation(operation_id, "user-1", "opencode")
        assert first == {"config": config, "auth": None}
        assert second == first
        # Non-consuming: verification may read the credentials while the row
        # stays redeemable as single-use proof.
        assert operation_id in repo.candidate_operations

        try:
            await service.read_candidate_operation(operation_id, "user-2", "opencode")
        except PermissionDeniedError as exc:
            assert exc.message_key == "errors.provider.forbidden"
        else:
            raise AssertionError("Candidate operations must only be readable by their owner")

        repo.candidate_operations[operation_id]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        try:
            await service.read_candidate_operation(operation_id, "user-1", "opencode")
        except NotFoundError as exc:
            assert exc.message_key == "errors.provider.config_not_found"
        else:
            raise AssertionError("Expired candidate operations must not resolve")

    asyncio.run(run())


def test_redeem_candidate_verification_accepts_matching_payload_and_consumes_it():
    async def run():
        repo = CandidateOperationRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        config = {"provider": {"x": {"options": {"apiKey": "secret-key"}}}}
        auth = {"x": {"key": "auth-secret"}}

        operation_id = await service.create_candidate_operation("user-1", "opencode", config, auth)

        # Same parsed objects with different key order still match.
        reordered_config = {"provider": {"x": {"options": {"apiKey": "secret-key"}}}}
        reordered_auth = {"x": {"key": "auth-secret"}}
        assert await service.redeem_candidate_verification(
            operation_id, "user-1", "opencode", reordered_config, reordered_auth) is True
        # The proof is single-use: redemption consumed the operation.
        assert operation_id not in repo.candidate_operations
        assert await service.redeem_candidate_verification(
            operation_id, "user-1", "opencode", config, auth) is False

    asyncio.run(run())


def test_redeem_candidate_verification_rejects_mismatch_missing_foreign_and_expired():
    async def run():
        repo = CandidateOperationRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        config = {"provider": {"x": {"options": {"apiKey": "secret-key"}}}}
        auth = {"x": {"key": "auth-secret"}}

        # Missing operations prove nothing.
        assert await service.redeem_candidate_verification(
            "missing", "user-1", "opencode", config, auth) is False

        # Mismatched credentials: the reused operation is untrusted and removed.
        mismatched = await service.create_candidate_operation("user-1", "opencode", config, auth)
        assert await service.redeem_candidate_verification(
            mismatched, "user-1", "opencode", config, {"x": {"key": "other"}}) is False
        assert mismatched not in repo.candidate_operations

        # Another actor's operation is neither redeemed nor revealed or deleted.
        foreign = await service.create_candidate_operation("user-2", "opencode", config, auth)
        assert await service.redeem_candidate_verification(
            foreign, "user-1", "opencode", config, auth) is False
        assert foreign in repo.candidate_operations

        # Expired operations cannot prove anything; the stale row is cleaned up.
        expired = await service.create_candidate_operation("user-1", "opencode", config, auth)
        repo.candidate_operations[expired]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert await service.redeem_candidate_verification(
            expired, "user-1", "opencode", config, auth) is False
        assert expired not in repo.candidate_operations

    asyncio.run(run())
