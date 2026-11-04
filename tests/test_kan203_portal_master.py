"""KAN-203: contrasena maestra del portal publico (privacidad de la casa y la camara Tapo).

Criterios de la incidencia:
- sin credenciales -> 401 (portal y API);
- con la contrasena maestra -> 200 y portal operativo (sus llamadas a la API);
- las apps siguen funcionando con su Bearer en api.loginea.com.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

PORTAL_HOST = "https://farofamilia.loginea.com"
API_HOST = "https://api.loginea.com"
PORTAL_PASSWORD = "maestra-de-prueba"
APP_TOKEN = "kan203-app-bearer-0123456789abcdef0123456789abcdef"
SESSION_SECRET = "kan203-session-secret-0123456789abcdef0123456789"


def _basic(user: str = "faro", password: str = PORTAL_PASSWORD) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture()
def portal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("FARO_PORTAL_USER", "faro")
    monkeypatch.setenv("FARO_PORTAL_PASS", PORTAL_PASSWORD)
    monkeypatch.setenv("AURA_LOCAL_TOKEN", APP_TOKEN)
    monkeypatch.setenv("AURA_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "kan203-pepper-0123456789abcdef")
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app, base_url=PORTAL_HOST)


@pytest.fixture()
def api(portal: TestClient) -> TestClient:
    return TestClient(main.app, base_url=API_HOST)


def test_portal_without_credentials_returns_401_and_challenges(portal: TestClient) -> None:
    response = portal.get("/")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic ")
    assert "no-store" in response.headers.get("cache-control", "")


def test_portal_with_wrong_password_stays_401(portal: TestClient) -> None:
    assert portal.get("/", headers=_basic(password="otra")).status_code == 401


def test_portal_with_master_password_returns_200(portal: TestClient) -> None:
    response = portal.get("/", headers=_basic())
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "private, no-store"
    assert "Authorization" in response.headers.get("vary", "")


def test_portal_master_password_opens_the_api(portal: TestClient) -> None:
    for path in (
        "/v1/patient-profile",
        "/v1/people",
        "/v1/camera/status",
        "/v1/camera/patrol",
        "/v1/camera/usage",
        "/v1/devices",
        "/v1/live-views",
        "/v1/location-sessions/active",
    ):
        response = portal.get(path, headers=_basic())
        assert response.status_code == 200, f"{path} -> {response.status_code}"
    assert portal.get("/v1/camera/capture", headers=_basic()).status_code in (200, 204)


def test_portal_master_password_does_not_leak_a_token(portal: TestClient) -> None:
    response = portal.get("/v1/patient-profile", headers=_basic())
    assert response.status_code == 200
    assert "faro1." not in response.text


def test_camera_routes_reject_anonymous_and_fake_bearer(portal: TestClient) -> None:
    assert portal.get("/v1/camera/status").status_code == 401
    assert portal.get("/v1/camera/preview").status_code == 401
    assert portal.get("/v1/camera/frame").status_code == 401
    fake = {"Authorization": "Bearer inventado"}
    assert portal.get("/v1/camera/status", headers=fake).status_code == 401
    assert portal.get("/v1/camera/preview", headers=fake).status_code == 401


def test_api_host_keeps_device_bearer(portal: TestClient, api: TestClient) -> None:
    bearer = {"Authorization": f"Bearer {APP_TOKEN}"}
    assert api.get("/v1/patient-profile").status_code == 401
    assert api.get("/v1/patient-profile", headers=bearer).status_code == 200
    assert api.get("/v1/camera/status", headers=bearer).status_code == 200
    assert api.get("/health").status_code == 200
    assert api.get("/.well-known/assetlinks.json").status_code == 200


def test_api_host_does_not_offer_basic_login(portal: TestClient, api: TestClient) -> None:
    # Solo el portal ofrece el reto Basic; en el host de las apps el anonimo es un 401 seco.
    response = api.get("/v1/people")
    assert response.status_code == 401
    assert "www-authenticate" not in response.headers


def test_public_infrastructure_paths_stay_public_on_both_hosts(portal: TestClient, api: TestClient) -> None:
    for client in (portal, api):
        assert client.get("/health").status_code == 200
        assert client.get("/.well-known/assetlinks.json").status_code == 200
        assert client.get("/download/faro-puente.apk").status_code in (200, 404)
        assert client.get("/assets/manifest.webmanifest").status_code == 200


def test_lookalike_paths_are_protected(portal: TestClient) -> None:
    assert portal.get("/assets-private/app.js").status_code == 401
    assert portal.get("/downloadx/faro.apk").status_code == 401
    assert portal.get("/.well-knownx/assetlinks.json").status_code == 401
