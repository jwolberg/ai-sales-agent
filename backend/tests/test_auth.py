"""HTTP Basic auth gate (ticket 0001).

Everything is protected by default; only the machine-to-machine webhooks and the liveness probe are
public (they authenticate by signature instead). Settings are monkeypatched per test so a local
backend/.env can't change the outcome.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings
from app.main import app

USER, PASSWORD = "operator", "s3cret-pw"


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _use(monkeypatch, **kwargs) -> TestClient:
    settings = Settings(_env_file=None, **kwargs)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    return TestClient(app)


@pytest.fixture
def secured(monkeypatch) -> TestClient:
    return _use(monkeypatch, dashboard_username=USER, dashboard_password=PASSWORD)


PROTECTED = [
    ("GET", "/api/calls"),
    ("GET", "/api/metrics"),
    ("GET", "/api/stream"),
    ("POST", "/api/sim/start"),
    ("POST", "/api/calls/some-id/send-payment-sms"),
    ("POST", "/voice/offer"),
    ("GET", "/voice/status"),
    ("GET", "/dashboard/"),
    ("GET", "/demo/"),
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_401_without_credentials(secured, method, path):
    resp = secured.request(method, path)
    assert resp.status_code == 401
    # The challenge header is what makes a browser show its login prompt for /dashboard.
    assert resp.headers["www-authenticate"].startswith("Basic ")


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_routes_401_with_wrong_password(secured, method, path):
    assert secured.request(method, path, headers=_basic(USER, "nope")).status_code == 401


def test_wrong_username_rejected(secured):
    assert secured.get("/api/calls", headers=_basic("admin", PASSWORD)).status_code == 401


@pytest.mark.parametrize(
    "header", ["Bearer abc", "Basic !!!not-base64!!!", "Basic " + base64.b64encode(b"x").decode()]
)
def test_malformed_authorization_rejected(secured, header):
    assert secured.get("/api/calls", headers={"Authorization": header}).status_code == 401


def test_valid_credentials_pass_through(secured):
    resp = secured.get("/voice/status", headers=_basic(USER, PASSWORD))
    assert resp.status_code == 200
    assert "ready" in resp.json()


def test_dashboard_ui_served_with_credentials(secured):
    resp = secured.get("/dashboard/", headers=_basic(USER, PASSWORD))
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/health"), ("POST", "/voice/twilio"), ("POST", "/payments/webhook")],
)
def test_public_routes_skip_basic_auth(secured, method, path):
    # Not 401: these authenticate by signature (Twilio/Stripe) or are the liveness probe.
    assert secured.request(method, path).status_code != 401


def test_public_prefix_does_not_leak_to_lookalike_paths(secured):
    # "/healthz" or "/payments/webhook-admin" must not ride on the allowlist.
    assert secured.get("/healthz").status_code == 401
    assert secured.post("/payments/webhook-admin").status_code == 401


def test_fails_closed_outside_development_when_password_unset(monkeypatch):
    client = _use(monkeypatch, environment="production", dashboard_password=None)
    resp = client.get("/api/calls")
    assert resp.status_code == 503
    assert "DASHBOARD_PASSWORD" in resp.json()["detail"]
    assert client.get("/health").status_code == 200


def test_open_in_development_when_password_unset(monkeypatch):
    client = _use(monkeypatch, environment="development", dashboard_password=None)
    assert client.get("/voice/status").status_code == 200


def test_credentials_checked_in_development_once_password_set(monkeypatch):
    client = _use(monkeypatch, environment="development", dashboard_password=PASSWORD)
    assert client.get("/voice/status").status_code == 401


def test_startup_warns_loudly_when_auth_is_off(monkeypatch, caplog):
    import logging

    from app import main

    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    with caplog.at_level(logging.WARNING, logger="app"):
        main.create_app()
    assert any("auth is OFF" in r.getMessage() for r in caplog.records)


def test_no_auth_warning_when_password_set(monkeypatch, caplog):
    import logging

    from app import main

    monkeypatch.setattr(
        main, "get_settings", lambda: Settings(_env_file=None, dashboard_password="pw")
    )
    with caplog.at_level(logging.WARNING, logger="app"):
        main.create_app()
    assert not any("auth is OFF" in r.getMessage() for r in caplog.records)
