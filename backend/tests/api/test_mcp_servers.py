from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.mcp_servers import get_mcp_server_service
from app.main import create_app


class Service:
    async def create(self, actor, data):
        return {'id': '00000000-0000-0000-0000-000000000001', 'name': data['name'], 'transport': {'type': 'stdio', 'env': []}}


def test_malformed_secret_request_validation_does_not_echo_sentinel_or_input(caplog):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id='u1', role='runner')
    app.dependency_overrides[get_mcp_server_service] = lambda: Service()
    client = TestClient(app)
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
