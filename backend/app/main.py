"""Kosmo API entry point."""

import logging

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routes import register_routers
from app.api import routes
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(title='Kosmo API', version='0.1.0')
    register_exception_handlers(application)
    register_routers(application, routes)
    logging.getLogger('kosmo').info('API started')

    return application


app = create_app()
