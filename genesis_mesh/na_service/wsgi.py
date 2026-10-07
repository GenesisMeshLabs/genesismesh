"""WSGI entry point for the Network Authority service.

Configuration is read from the environment by ``settings.load_settings``; see
that module for the variables. With no v0.60 variables set the NA runs exactly
as before (SQLite, key file). The app itself is built by
``app_factory.build_app``, which ``genesis-mesh na start --env-file`` shares
(v1.2.0).
"""

from genesis_mesh.na_service.app_factory import build_app
from genesis_mesh.na_service.settings import load_settings
from genesis_mesh.observability import configure_logging


configure_logging()

settings = load_settings()

app = build_app(settings)
