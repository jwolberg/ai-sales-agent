"""Small hardening items (ticket 0012): /demo scope, /health surface, webhook error detail."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings
from app.main import app
from app.payments import webhook


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # Open auth (dev, no password) so these tests isolate the routes themselves.
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(_env_file=None))
    return TestClient(app)


@pytest.mark.parametrize("path", ["/demo/", "/demo/index.html", "/demo/client.js"])
def test_demo_serves_its_own_files(client, path):
    assert client.get(path).status_code == 200


def test_demo_serves_its_audio(client):
    resp = client.get("/demo/audio/dial.mp3")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/")


@pytest.mark.parametrize(
    "path",
    [
        "/demo/dashboard-app/package.json",
        "/demo/dashboard-app/package-lock.json",
        "/demo/dashboard-app/src/App.jsx",
        "/demo/dashboard-app/vite.config.js",
        "/demo/dashboard/index.html",
        "/demo/audio/../dashboard-app/package.json",
    ],
)
def test_demo_does_not_expose_the_rest_of_frontend(client, path):
    assert client.get(path).status_code == 404


def test_health_exposes_only_status_and_version(client):
    body = client.get("/health").json()
    assert set(body) == {"status", "version"}


def test_stripe_bad_signature_detail_is_generic(client, monkeypatch):
    monkeypatch.setattr(
        webhook, "get_settings", lambda: Settings(_env_file=None, stripe_webhook_secret="whsec_x")
    )
    resp = client.post("/payments/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid Stripe signature"
