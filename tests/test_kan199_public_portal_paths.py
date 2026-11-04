from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.fixture()
def client() -> TestClient:
    return TestClient(main.app, base_url="https://farofamilia.loginea.com")


def _basic(user: str = "faro", password: str = "secreto") -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_portal_open_when_password_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FARO_PORTAL_PASS", raising=False)
    assert client.get("/").status_code == 200


def test_portal_document_requires_auth_but_assets_stay_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # KAN-203: el documento del portal ya no es publico (antes KAN-199 lo abria para la TWA).
    monkeypatch.setenv("FARO_PORTAL_PASS", "secreto")
    monkeypatch.setenv("AURA_SESSION_SECRET", "test-session-secret-0123456789abcdef0123456789abcdef")
    assert client.get("/").status_code == 401
    assert client.get("/", headers=_basic(password="mal")).status_code == 401
    assert client.get("/", headers=_basic()).status_code == 200
    assert client.get("/assets/manifest.webmanifest").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/v1/patient-profile").status_code == 401
    assert client.get("/v1/camera/status").status_code == 401


def test_lookalike_paths_are_not_public(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FARO_PORTAL_PASS", "secreto")
    assert client.get("/assets-private/x").status_code == 401
    assert client.get("/healthz").status_code == 401
    assert client.get("/v1/people").status_code == 401


def test_public_paths_stay_reachable_with_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FARO_PORTAL_PASS", "secreto")
    assert client.get("/health").status_code == 200
    assert client.get("/.well-known/assetlinks.json").status_code == 200


def test_download_path_is_public_but_not_camera(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FARO_PORTAL_PASS", "secreto")
    download = client.get("/download/faro-puente.apk")
    assert download.status_code in (200, 404)
    assert client.get("/v1/camera/status").status_code == 401
