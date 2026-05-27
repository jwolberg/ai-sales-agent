"""FastAPI application entry point."""

from fastapi import FastAPI

from app import __version__
from app.config import get_settings


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

    return app


app = create_app()
