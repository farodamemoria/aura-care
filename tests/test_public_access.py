"""KAN-31: cierre de la autenticacion publica de desarrollo.

Cubre los criterios de aceptacion: sin token de desarrollo conocido, identidad
valida por usuario y circulo familiar, aislamiento entre familias y pruebas
negativas de acceso anonimo, token invalido y acceso cruzado.
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

TOKEN = "test-portal-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
LEGACY_TOKEN = "local-development-only"
SESSION_SECRET = "session-secret-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
PROTECTED_PATHS = (
    "/v1/onboarding",
    "/v1/events",
    "/v1/location-sessions/active",
    "/v1/people",
    "/v1/reviews",
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.delenv("AURA_CARE_CIRCLE_ID", raising=False)
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def test_configured_token_opens_protected_endpoints(client: TestClient) -> None:
    assert client.get("/v1/people", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


@pytest.mark.parametrize("path", PROTECTED_PATHS)
def test_anonymous_access_is_rejected(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED_PATHS)
def test_legacy_development_token_is_rejected(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"Authorization": f"Bearer {LEGACY_TOKEN}"})
    assert response.status_code == 401


def test_invalid_token_is_rejected(client: TestClient) -> None:
    assert client.get("/v1/people", headers={"Authorization": "Bearer wrong-token"}).status_code == 401


def test_missing_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AURA_LOCAL_TOKEN", raising=False)
    response = TestClient(main.app).get("/v1/people", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503


def test_legacy_token_as_configuration_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", LEGACY_TOKEN)
    response = TestClient(main.app).get(
        "/v1/people", headers={"Authorization": f"Bearer {LEGACY_TOKEN}"}
    )
    assert response.status_code == 503


def test_short_bootstrap_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", "short-token")
    response = TestClient(main.app).get(
        "/v1/people", headers={"Authorization": "Bearer short-token"}
    )
    assert response.status_code == 503


def test_session_token_grants_circle_identity(client: TestClient) -> None:
    issued = client.post(
        "/v1/auth/session",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"role": "caregiver", "subject": "familiar-1", "ttl_seconds": 600},
    )
    assert issued.status_code == 201
    body = issued.json()
    assert body["care_circle_id"] == "local-care-circle"
    response = client.get(
        "/v1/people", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert response.status_code == 200


def test_session_endpoint_requires_bootstrap_token(client: TestClient) -> None:
    legacy = client.post(
        "/v1/auth/session",
        headers={"Authorization": f"Bearer {LEGACY_TOKEN}"},
        json={"role": "family"},
    )
    assert legacy.status_code == 401
    token, _ = main.issue_session_token("local-care-circle", "family", "familiar-1", 600)
    with_session = client.post(
        "/v1/auth/session",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "family"},
    )
    assert with_session.status_code == 401


def test_expired_session_token_is_rejected(client: TestClient) -> None:
    token, _ = main.issue_session_token("local-care-circle", "family", "familiar-1", -60)
    response = client.get("/v1/people", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_tampered_session_token_is_rejected(client: TestClient) -> None:
    token, _ = main.issue_session_token("local-care-circle", "family", "familiar-1", 600)
    response = client.get("/v1/people", headers={"Authorization": f"Bearer {token}x"})
    assert response.status_code == 401


def test_session_token_from_another_care_circle_is_rejected(client: TestClient) -> None:
    token, _ = main.issue_session_token("otra-familia", "family", "intruso", 600)
    response = client.get("/v1/people", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_frontend_ships_no_default_token() -> None:
    app_js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "auraToken" in app_js
    assert LEGACY_TOKEN not in app_js
    assert "local-development" not in app_js


def test_source_has_no_development_fallback() -> None:
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert LEGACY_TOKEN not in source
    assert 'os.getenv("AURA_LOCAL_TOKEN",' not in source
