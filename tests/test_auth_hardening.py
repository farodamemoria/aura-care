"""KAN-31 negative/positive authentication tests for the AURA Care backend.

These cases cover the acceptance criteria that can be validated locally:
- the historic development token must never authorize any endpoint;
- sensitive endpoints must reject anonymous and invalid bearers;
- a valid bearer is accepted;
- a missing server-side token/pepper configuration fails closed.
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

KNOWN_DEV_TOKEN = "local-development-only"
STRONG_TOKEN = "test-family-circle-token-9f3c4b"

SENSITIVE_PATHS = [
    "/v1/account",
    "/v1/people",
    "/v1/events",
    "/v1/onboarding",
    "/v1/patient-profile",
    "/v1/reviews",
    "/v1/care-contacts",
    "/v1/emergency-alerts",
    "/v1/memories",
    "/v1/whatsapp/statuses",
]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", STRONG_TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    return TestClient(main.app)


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_version_is_public(client: TestClient) -> None:
    assert client.get("/v1/version").status_code == 200


@pytest.mark.parametrize("path", SENSITIVE_PATHS)
def test_sensitive_endpoints_reject_anonymous(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", SENSITIVE_PATHS)
def test_sensitive_endpoints_reject_known_dev_token(client: TestClient, path: str) -> None:
    response = client.get(path, headers={"Authorization": f"Bearer {KNOWN_DEV_TOKEN}"})
    assert response.status_code == 401


def test_invalid_bearer_is_rejected(client: TestClient) -> None:
    response = client.get("/v1/people", headers={"Authorization": "Bearer not-the-token"})
    assert response.status_code == 401


def test_non_bearer_scheme_is_rejected(client: TestClient) -> None:
    response = client.get("/v1/people", headers={"Authorization": f"Basic {STRONG_TOKEN}"})
    assert response.status_code == 401


def test_valid_bearer_is_accepted(client: TestClient) -> None:
    response = client.get("/v1/people", headers={"Authorization": f"Bearer {STRONG_TOKEN}"})
    assert response.status_code == 200


def test_missing_server_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AURA_LOCAL_TOKEN", raising=False)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    unconfigured = TestClient(main.app)
    for credential in (KNOWN_DEV_TOKEN, STRONG_TOKEN):
        response = unconfigured.get("/v1/people", headers={"Authorization": f"Bearer {credential}"})
        assert response.status_code == 401


def test_credential_hash_requires_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AURA_CREDENTIAL_PEPPER", raising=False)
    monkeypatch.delenv("AURA_LOCAL_TOKEN", raising=False)
    with pytest.raises(Exception):
        main.credential_hash("device-secret")


def test_credential_hash_never_uses_the_dev_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AURA_CREDENTIAL_PEPPER", raising=False)
    monkeypatch.setenv("AURA_LOCAL_TOKEN", KNOWN_DEV_TOKEN)
    with pytest.raises(Exception):
        main.credential_hash("device-secret")


def test_source_has_no_embedded_dev_token() -> None:
    for relative in ("app/main.py", "web/assets/app.js"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert KNOWN_DEV_TOKEN not in text, f"dev token fallback still present in {relative}"


def test_credential_hash_depends_on_the_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "pepper-a")
    first = main.credential_hash("device-secret")
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "pepper-b")
    second = main.credential_hash("device-secret")
    assert first != second
