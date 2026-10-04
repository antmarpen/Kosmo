from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.mcp_servers import get_mcp_server_service
from app.main import create_app


class Service:
    async def create(self, actor, data):
        return {'id': '00000000-0000-0000-0000-000000000001', 'name': data['name'], 'transport': {'type': 'stdio', 'env': []}}

    async def list_visible(self, user_id):
        return [{'id': 'id1', 'name': 'tool', 'owner_user_id': user_id, 'visibility': 'personal', 'group_id': None}]

    async def get_visible(self, user_id, server_id):
        return {'id': server_id, 'name': 'tool', 'owner_user_id': user_id, 'visibility': 'personal', 'group_id': None, 'updated_at': None,
                'transport': {'type': 'stdio', 'command': 'tool', 'args': [],
                              'env': [{'name': 'TOKEN', 'secret': True, 'is_set': True,
                                       'value': 'SECRET-SENTINEL', 'ciphertext': 'CIPHERTEXT-SENTINEL'}]}}


def test_malformed_secret_request_validation_does_not_echo_sentinel_or_input(caplog):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id='u1', role='runner')
    app.dependency_overrides[get_mcp_server_service] = lambda: Service()
    client = TestClient(app)
    listing = client.get('/mcp-servers')
    assert listing.status_code == 200
    assert 'transport' not in listing.json()[0]
    detail = client.get('/mcp-servers/id1')
    assert detail.status_code == 200
    entry = detail.json()['transport']['env'][0]
    assert entry == {'name': 'TOKEN', 'secret': True, 'is_set': True}
    assert 'SECRET-SENTINEL' not in detail.text and 'CIPHERTEXT-SENTINEL' not in detail.text
    assert 'value' not in entry and 'ciphertext' not in detail.text
    sentinel = 'SENTINEL-SECRET'
    response = client.post('/mcp-servers', json={'name': 'x', 'transport': {
        'type': 'stdio', 'command': 'tool', 'args': [], 'env': [
            {'name': 'TOKEN', 'secret': True, 'action': 'replace', 'value': sentinel, 'unexpected': True}]}})
    assert response.status_code == 422
    assert sentinel not in response.text
    assert 'input' not in response.text
    assert sentinel not in caplog.text
    assert client.post('/mcp-servers', json={'name': 'x', 'transport': {
        'type': 'stdio', 'command': 'tool', 'args': [], 'env': [], 'url': 'https://bad.test'}}).status_code == 422
    client.close()
