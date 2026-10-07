"""FastAPI application entry point."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.auth import BasicAuthMiddleware
from app.config import get_settings
from app.dashboard.router import router as dashboard_router
from app.logs import configure_logging
from app.payments.webhook import router as payments_router
from app.voice.server import router as voice_router

# Repo root is two levels up from this file: backend/app/main.py -> repo root.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
# Prefer the built React call-center dashboard (IR7-T4); fall back to the legacy static page.
_DASHBOARD_APP_DIST = FRONTEND_DIR / "dashboard-app" / "dist"
DASHBOARD_DIR = _DASHBOARD_APP_DIST if _DASHBOARD_APP_DIST.is_dir() else FRONTEND_DIR / "dashboard"


class _DemoFiles(StaticFiles):
    """The voice demo shares frontend/ with the dashboard's source tree, so serve only the demo's
    own files — not package.json, the lockfile, or dashboard-app/src (ticket 0012)."""

    _FILES = frozenset({".", "index.html", "client.js"})

    async def get_response(self, path: str, scope):
        if path not in self._FILES and not path.startswith("audio/"):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.dashboard_password:
        # Open in development, 503 elsewhere (app/auth.py) — either way, make it impossible to miss.
        logging.getLogger(__name__).warning(
            "operator auth is OFF: DASHBOARD_PASSWORD is unset (environment=%s; %s)",
            settings.environment,
            "routes are open" if settings.environment == "development" else "routes return 503",
        )
    app = FastAPI(title=settings.app_name, version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe used by tooling and deploy checks. Public, so it reveals nothing about
        the deployment beyond being up."""
        return {"status": "ok", "version": __version__}

    # Outermost layer: gates every route + static mount except the public webhooks/probe.
    app.add_middleware(BasicAuthMiddleware)

    app.include_router(voice_router)
    app.include_router(dashboard_router)
    app.include_router(payments_router)

    # Serve the observability dashboard UI at /dashboard (mounted before /demo so the
    # nested frontend/dashboard dir isn't shadowed by the /demo mount).
    if DASHBOARD_DIR.is_dir():
        app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
    # Serve the voice demo client at /demo (if the frontend has been added).
    if FRONTEND_DIR.is_dir():
        app.mount("/demo", _DemoFiles(directory=FRONTEND_DIR, html=True), name="demo")

    return app


app = create_app()
