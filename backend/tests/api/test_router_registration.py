from __future__ import annotations

import importlib
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.api.routes import discover_routers, register_routers
from app.main import create_app


def make_package(tmp_path: Path, modules: dict[str, str]) -> str:
    package_name = f'fake_routes_{uuid.uuid4().hex}'
    package_dir = tmp_path / package_name
    package_dir.mkdir()
    (package_dir / '__init__.py').write_text('')
    for module_name, source in modules.items():
        (package_dir / f'{module_name}.py').write_text(textwrap.dedent(source))
    sys.path.insert(0, str(tmp_path))
    importlib.invalidate_caches()
    return package_name


def test_convention_fails_for_module_without_router(tmp_path: Path) -> None:
    package_name = make_package(tmp_path, {'broken': 'value = 1'})
    try:
        with pytest.raises(RuntimeError, match=f'{package_name}.broken'):
            discover_routers(importlib.import_module(package_name))
    finally:
        sys.path.remove(str(tmp_path))
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(f'{package_name}.'):
                del sys.modules[name]


def test_discovery_imports_routers_from_fake_package(tmp_path: Path) -> None:
    package_name = make_package(tmp_path, {
        'first': "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/first')\ndef first(): return {'ok': True}",
        '_private': 'value = 1',
    })
    try:
        modules = discover_routers(importlib.import_module(package_name))
        assert [module.__name__ for module in modules] == [f'{package_name}.first']
    finally:
        sys.path.remove(str(tmp_path))
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(f'{package_name}.'):
                del sys.modules[name]


def test_health_route_is_discovered_and_included() -> None:
    application = create_app()
    assert '/healthz' in application.openapi()['paths']


def test_added_route_module_is_registered_without_other_changes(tmp_path: Path) -> None:
    package_name = make_package(tmp_path, {
        'extra': "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/auto')\ndef auto(): return {'ok': True}",
    })
    try:
        application = FastAPI()
        register_routers(application, importlib.import_module(package_name))
        assert '/auto' in application.openapi()['paths']
    finally:
        sys.path.remove(str(tmp_path))
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(f'{package_name}.'):
                del sys.modules[name]
