import asyncio
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.domain.mcp_servers.service import McpServerService
from app.domain.mcp_servers.repository import McpServerRepository
from shared.errors import PermissionDeniedError, ValidationFailedError


class Repo:
    def __init__(self):
        self.rows = []
        self.memberships_by_user = {}
        self.roles = {}

    async def memberships(self, user_id):
        return list(self.memberships_by_user.get(user_id, {}))

    async def membership_role(self, user_id, group_id):
        return self.memberships_by_user.get(user_id, {}).get(group_id)

    async def visible_candidates(self, user_id, groups):
        return [r for r in self.rows if (r.visibility == 'personal' and r.owner_user_id == user_id)
                or (r.visibility == 'group' and r.group_id in groups) or r.visibility == 'global']

    async def by_id(self, entity_id):
        return next((r for r in self.rows if r.id == entity_id), None)

    async def name_conflict(self, owner, name, visibility, group_id, *, exclude_id=None):
        return False

    async def create(self, row, *, secret_values=None):
        row.id = f'00000000-0000-0000-0000-{len(self.rows) + 1:012d}'
        row.secret_ciphertext = {k: Fernet(KEY).encrypt(v.encode()).decode() for k, v in (secret_values or {}).items()}
        self.rows.append(row)
        return row

    async def update(self, row, *, secret_values=None, retained_ciphertext=None, **changes):
        for key, value in changes.items():
            setattr(row, key, value)
        if secret_values is not None:
            row.secret_ciphertext = {**(retained_ciphertext or {}), **{k: Fernet(KEY).encrypt(v.encode()).decode() for k, v in secret_values.items()}}
        return row

    async def delete(self, entity_id):
        return True


KEY = Fernet.generate_key().decode()


def actor(user_id='u1', role='runner'):
    return SimpleNamespace(id=user_id, role=role)


def test_create_encrypts_secret_and_detail_never_returns_secret_or_ciphertext(monkeypatch):
    async def run():
        monkeypatch.setattr('app.domain.mcp_servers.service.settings.config_encryption_key', KEY)
        repo = Repo()
        service = McpServerService(repo)
        detail = await service.create(actor(), {'name': 'tools', 'transport': {
            'type': 'stdio', 'command': 'tool', 'args': [], 'env': [
                {'name': 'TOKEN', 'secret': True, 'action': 'replace', 'value': 'SENTINEL'}]}})
        ciphertext = repo.rows[0].secret_ciphertext['TOKEN']
        assert ciphertext != 'SENTINEL'
        assert Fernet(KEY).decrypt(ciphertext.encode()).decode() == 'SENTINEL'
        assert 'SENTINEL' not in repr(repo.rows[0].safe_config)
        assert detail['transport']['env'] == [{'name': 'TOKEN', 'secret': True, 'is_set': True}]
        assert 'secret_ciphertext' not in repr(detail) and 'value' not in repr(detail)
    asyncio.run(run())


def test_repository_encrypts_secret_bytes_before_persistence(monkeypatch):
    monkeypatch.setattr('app.domain.mcp_servers.repository.settings.config_encryption_key', KEY)
    ciphertext = McpServerRepository.encrypt_secrets({'TOKEN': 'DB-BYTES-SENTINEL'})['TOKEN']
    assert ciphertext != 'DB-BYTES-SENTINEL'
    assert Fernet(KEY).decrypt(ciphertext.encode()) == b'DB-BYTES-SENTINEL'


def test_entry_actions_exact_set_transport_switch_and_duplicate_rejection(monkeypatch):
    async def run():
        monkeypatch.setattr('app.domain.mcp_servers.service.settings.config_encryption_key', KEY)
        repo = Repo()
        service = McpServerService(repo)
        entry = {'name': 'TOKEN', 'secret': True, 'action': 'replace', 'value': 'one'}
        created = await service.create(actor(), {'name': 'tools', 'transport': {'type': 'stdio', 'command': 'tool', 'args': [], 'env': [entry]}})
        ident = created['id']
        kept = await service.update(actor(), ident, {'transport': {'type': 'stdio', 'command': 'tool', 'args': [], 'env': [
            {'name': 'TOKEN', 'secret': True, 'action': 'keep'}]}})
        assert kept['transport']['env'] == [{'name': 'TOKEN', 'secret': True, 'is_set': True}]
        replaced = await service.update(actor(), ident, {'transport': {'type': 'stdio', 'command': 'tool', 'args': [], 'env': [
            {'name': 'TOKEN', 'secret': True, 'action': 'replace', 'value': ''}]}})
        assert replaced['transport']['env'][0]['is_set'] is True
        removed = await service.update(actor(), ident, {'transport': {'type': 'stdio', 'command': 'tool', 'args': [], 'env': [
            {'name': 'TOKEN', 'secret': True, 'action': 'remove'}]}})
        assert removed['transport']['env'] == []
        before = repo.rows[0].transport_type
        with pytest.raises(ValidationFailedError):
            await service.update(actor(), ident, {'transport': {'type': 'stdio', 'command': 'tool', 'args': [], 'env': [
                {'name': 'X', 'secret': False, 'action': 'replace', 'value': 'a'},
                {'name': 'X', 'secret': False, 'action': 'replace', 'value': 'b'}]}})
        assert repo.rows[0].transport_type == before
        with pytest.raises(ValidationFailedError):
            await service.update(actor(), ident, {'transport': {'type': 'http', 'url': 'https://example.test', 'headers': [
                {'name': 'Authorization', 'secret': True, 'action': 'keep'}]}})
        switched = await service.update(actor(), ident, {'transport': {'type': 'http', 'url': 'https://example.test/mcp', 'headers': [
            {'name': 'Authorization', 'secret': True, 'action': 'replace', 'value': 'Bearer one'}]}})
        assert switched['transport']['type'] == 'http'
        with pytest.raises(ValidationFailedError):
            await service.create(actor(), {'name': 'bad-url', 'transport': {'type': 'http', 'url': 'https://user:pass@example.test', 'headers': []}})
    asyncio.run(run())


def test_encryption_key_failure_fails_closed(monkeypatch):
    async def run():
        monkeypatch.setattr('app.domain.mcp_servers.service.settings.config_encryption_key', '')
        with pytest.raises(ValidationFailedError):
            await McpServerService(Repo()).create(actor(), {'name': 'tools', 'transport': {
                'type': 'stdio', 'command': 'tool', 'args': [], 'env': [
                    {'name': 'TOKEN', 'secret': True, 'action': 'replace', 'value': 'SENTINEL'}]}})
    asyncio.run(run())


def test_scope_creation_and_list_authorization_match_provider_policy(monkeypatch):
    async def run():
        monkeypatch.setattr('app.domain.mcp_servers.service.settings.config_encryption_key', KEY)
        repo = Repo()
        service = McpServerService(repo)
        transport = {'type': 'stdio', 'command': 'tool', 'args': [], 'env': []}
        with pytest.raises(PermissionDeniedError):
            await service.create(actor(), {'name': 'global', 'visibility': 'global', 'transport': transport})
        repo.memberships_by_user['u1'] = {'g1': 'member'}
        with pytest.raises(PermissionDeniedError):
            await service.create(actor(), {'name': 'group', 'visibility': 'group', 'group_id': 'g1', 'transport': transport})
        repo.memberships_by_user['u1'] = {'g1': 'group_manager'}
        created = await service.create(actor(), {'name': 'group', 'visibility': 'group', 'group_id': 'g1', 'transport': transport})
        listed = await service.list_visible('u1')
        assert listed[0]['id'] == created['id']
        assert 'transport' not in listed[0]
    asyncio.run(run())
