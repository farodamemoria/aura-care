"""Public-access regression tests for the AURA Care portal.

After reverting KAN-31 (auth hardening), the portal must open without any
authentication prompt: the frontend ships a default token and the backend
accepts it. The bearer mechanism is kept so it can be locked down later.
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

DEFAULT_TOKEN = "local-development-only"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(main.app)


def test_default_token_opens_protected_endpoints(client: TestClient) -> None:
    response = client.get("/v1/people", headers={"Authorization": f"Bearer {DEFAULT_TOKEN}"})
    assert response.status_code == 200


def test_invalid_token_is_rejected(client: TestClient) -> None:
    response = client.get("/v1/people", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_frontend_ships_default_token() -> None:
    app_js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert DEFAULT_TOKEN in app_js
