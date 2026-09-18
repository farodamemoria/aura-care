"""Auth regression tests for the AURA Care portal.

The backend refuses to serve protected data unless `AURA_LOCAL_TOKEN` is
configured (fail-closed). The private portal ships a bearer token.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "test-portal-token"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    return TestClient(main.app)


def test_configured_token_opens_protected_endpoints(client: TestClient) -> None:
    assert client.get("/v1/people", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_invalid_token_is_rejected(client: TestClient) -> None:
    assert client.get("/v1/people", headers={"Authorization": "Bearer wrong-token"}).status_code == 401


def test_missing_token_is_rejected(client: TestClient) -> None:
    assert client.get("/v1/people").status_code == 401


def test_missing_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AURA_LOCAL_TOKEN", raising=False)
    response = TestClient(main.app).get(
        "/v1/people", headers={"Authorization": "Bearer anything"}
    )
    assert response.status_code == 503


def test_frontend_ships_a_bearer_token() -> None:
    app_js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "auraToken" in app_js
