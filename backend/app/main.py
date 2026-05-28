"""FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.dashboard.router import router as dashboard_router
from app.voice.server import router as voice_router

# Repo root is two levels up from this file: backend/app/main.py -> repo root.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
DASHBOARD_DIR = FRONTEND_DIR / "dashboard"


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe used by tooling and deploy checks."""
        config = get_settings()
        return {
            "status": "ok",
            "app": config.app_name,
            "version": __version__,
            "environment": config.environment,
        }

    app.include_router(voice_router)
    app.include_router(dashboard_router)

    # Serve the observability dashboard UI at /dashboard (mounted before /demo so the
    # nested frontend/dashboard dir isn't shadowed by the /demo mount).
    if DASHBOARD_DIR.is_dir():
        app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
    # Serve the voice demo client at /demo (if the frontend has been added).
    if FRONTEND_DIR.is_dir():
        app.mount("/demo", StaticFiles(directory=FRONTEND_DIR, html=True), name="demo")

    return app


app = create_app()
