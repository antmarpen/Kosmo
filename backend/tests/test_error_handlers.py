import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from app.api.errors import register_exception_handlers
from shared.errors import ErrorDetail, KosmoError, ValidationFailedError


@pytest.fixture
async def app():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get('/kosmo')
    async def kosmo_error():
        raise KosmoError('errors.example', {'field': 'name'}, [ErrorDetail('errors.required')], 'EXAMPLE', 400, 'internal-only')

    @app.get('/validation')
    async def validation_error():
        raise ValidationFailedError('errors.invalid', details=[ErrorDetail('errors.one'), ErrorDetail('errors.two')])

    @app.get('/unexpected')
    async def unexpected_error():
        raise RuntimeError('secret-stack-marker')

    return app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        yield client


@pytest.mark.anyio
async def test_kosmo_error_has_exact_contract(client):
    response = await client.get('/kosmo')
    assert response.status_code == 400
    assert response.json() == {
        'code': 'EXAMPLE', 'message_key': 'errors.example', 'params': {'field': 'name'},
        'details': [{'message_key': 'errors.required', 'params': {}}],
    }


@pytest.mark.anyio
async def test_unexpected_error_is_sanitized_and_logged(client, caplog):
    import logging
    with caplog.at_level(logging.ERROR):
        response = await client.get('/unexpected')
    assert response.status_code == 500
    assert response.json() == {'code': 'INTERNAL_ERROR', 'message_key': 'errors.internal', 'params': {}, 'details': []}
    assert 'secret-stack-marker' not in response.text
    assert 'secret-stack-marker' in caplog.text


@pytest.mark.anyio
async def test_validation_error_serializes_multiple_details(client):
    response = await client.get('/validation')
    assert response.status_code == 422
    assert response.json()['details'] == [
        {'message_key': 'errors.one', 'params': {}}, {'message_key': 'errors.two', 'params': {}}
    ]
