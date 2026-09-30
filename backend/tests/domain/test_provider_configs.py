import asyncio

from cryptography.fernet import Fernet

from app.domain.provider_configs.service import ProviderConfigService


class ConfigRepository:
    def __init__(self):
        self.rows = []
        self.row = None

    async def save(self, user_id, provider, config_ciphertext, auth_ciphertext,
                   visibility="personal", group_id=None):
        self.row = ConfigRow(id="config-1", user_id=user_id, provider=provider,
                             config_ciphertext=config_ciphertext, auth_ciphertext=auth_ciphertext,
                             visibility=visibility, group_id=group_id, updated_at=None)
        self.rows = [r for r in self.rows if not (r.user_id == user_id and r.provider == provider
                     and r.visibility == visibility and r.group_id == group_id)] + [self.row]
        return self.row

    async def get(self, user_id, provider):
        return next((r for r in self.rows if r.user_id == user_id and r.provider == provider
                     and r.visibility == "personal"), None)

    async def candidates(self, user_id, provider, group_ids):
        return [r for r in self.rows if r.provider == provider and
                ((r.visibility == "personal" and r.user_id == user_id) or r.visibility == "global" or
                 (r.visibility == "group" and r.group_id in group_ids))]

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
        await service.replace("user-1", "opencode", config, auth)

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
        await service.replace("user-1", "opencode", b'{"model":"m"}', None)
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
                              visibility="global")
        await service.replace("admin", "opencode", b'{"model":"group"}', None,
                              visibility="group", group_id="g1")
        await service.replace("runner", "opencode", b'{"model":"personal"}', None)
        files = await service.resolve_files("runner", "opencode", ["g1"])
        assert b'personal' in files["opencode.json"]

    asyncio.run(run())


def test_ambiguous_group_provider_configs_raise_structured_conflict():
    from shared.errors import ConflictError

    async def run():
        repo = ConfigRepository()
        service = ProviderConfigService(repo, Fernet.generate_key().decode())
        await service.replace("owner-1", "opencode", b'{"model":"group-a"}', None,
                              visibility="group", group_id="g1")
        await service.replace("owner-2", "opencode", b'{"model":"group-b"}', None,
                              visibility="group", group_id="g2")
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
                              visibility="group", group_id="team-1")
        await service.replace("admin", "opencode", b'{"model":"global"}', None,
                              visibility="global")
        group_files = await service.resolve_files("member", "opencode", ["team-1"])
        assert b'group' in group_files["opencode.json"]
        global_files = await service.resolve_files("outsider", "opencode", [])
        assert b'global' in global_files["opencode.json"]

    asyncio.run(run())
