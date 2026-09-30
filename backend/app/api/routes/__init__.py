"""Dynamic API route discovery and registration."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Any

from fastapi import APIRouter, FastAPI


def discover_routers(package: ModuleType) -> list[ModuleType]:
    """Import route modules in a package, requiring each public module's router."""
    package_path: Any = package.__path__
    discovered: list[ModuleType] = []
    for module_info in pkgutil.iter_modules(package_path, f'{package.__name__}.'):
        short_name = module_info.name.rsplit('.', 1)[-1]
        if short_name.startswith('_'):
            continue
        module = importlib.import_module(module_info.name)
        if not isinstance(getattr(module, 'router', None), APIRouter):
            raise RuntimeError(f'Route module {module_info.name} must expose an APIRouter named router')
        discovered.append(module)
    return discovered


def register_routers(application: FastAPI, package: ModuleType) -> None:
    """Discover and include every router exposed by a route package."""
    for module in discover_routers(package):
        application.include_router(module.router)
