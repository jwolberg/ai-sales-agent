"""Brand is configuration, not copy (ticket 0011).

The company name comes from ``company_name`` (config.toml / env) everywhere the caller sees it, and
no real company's name ships in product-facing files.
"""

import re
from pathlib import Path

import pytest

from app.config import Settings
from app.payments.sms import payment_sms_body

REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_BRANDS = re.compile(r"nerdy|varsity|nerd ai", re.IGNORECASE)


def test_payment_sms_body_uses_configured_company():
    body = payment_sms_body(Settings(_env_file=None, company_name="Zed Tutoring"), "https://pay/x")
    assert "Zed Tutoring" in body and "https://pay/x" in body


def test_default_company_is_neutral():
    assert not _REAL_BRANDS.search(Settings(_env_file=None).company_name)


def test_engine_auto_text_uses_configured_company():
    from app.agent.intent_engine import IntentRouterEngine

    sent = []

    class _Sms:
        def send(self, to, body):
            sent.append(body)
            return "SM1"

    engine = IntentRouterEngine.__new__(IntentRouterEngine)
    engine.settings = Settings(_env_file=None, company_name="Zed Tutoring")
    engine._sms_sender, engine.recorder = _Sms(), None

    class _Link:
        url = "https://pay/x"

    assert engine._try_text_link("+15551234567", _Link())
    assert sent == [payment_sms_body(engine.settings, "https://pay/x")]


def test_dashboard_send_uses_configured_company(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.agent.recorder import CallRecorder
    from app.dashboard import router as dash
    from app.db.models import Base
    from app.db.session import get_db
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = sessions()
    rec = CallRecorder(db, channel="web")
    rec.record_payment(
        leaf="test_prep/SAT",
        amount=85.0,
        currency="usd",
        kind="link",
        provider_ref="plink_1",
        url="https://pay/x",
    )
    db.close()

    sent = []

    class _Sms:
        def send(self, to, body):
            sent.append(body)
            return "SM1"

    settings = Settings(_env_file=None, company_name="Zed Tutoring")
    monkeypatch.setattr(dash, "get_settings", lambda: settings)
    monkeypatch.setattr(dash, "get_sms_sender", lambda _s: _Sms())

    def _db():
        s = sessions()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    try:
        resp = TestClient(app).post(
            f"/api/calls/{rec.call_id}/send-payment-sms", json={"phone": "+15551234567"}
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert sent and "Zed Tutoring" in sent[0]


_PRODUCT_FILES = [
    *sorted((REPO_ROOT / "backend" / "app").rglob("*.py")),
    REPO_ROOT / "backend" / "config.toml",
    *sorted((REPO_ROOT / "data" / "kb").glob("*.md")),
    REPO_ROOT / "data" / "pricing" / "pricing.yaml",
    REPO_ROOT / "data" / "personas" / "personas.yaml",
    REPO_ROOT / "frontend" / "index.html",
    REPO_ROOT / "frontend" / "client.js",
    REPO_ROOT / "frontend" / "dashboard-app" / "index.html",
    REPO_ROOT / "frontend" / "dashboard-app" / "package.json",
    *sorted((REPO_ROOT / "frontend" / "dashboard-app" / "src").glob("*")),
]


@pytest.mark.parametrize("path", _PRODUCT_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_real_company_name_in_product_files(path):
    hits = [
        f"{i}: {line.strip()}"
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if _REAL_BRANDS.search(line)
    ]
    assert not hits, hits
