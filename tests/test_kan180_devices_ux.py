"""KAN-180 - rediseno UX/UI y analisis funcional de la seccion Dispositivos."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan180-token-4a7c1e9b6d2f8035c5e7a1b9d3f6c2"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    monkeypatch.setattr(main, "_LAST_CAMERA_FRAME", {"at": None})
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _pair(client: TestClient, role: str = "family") -> dict:
    invite = client.post("/v1/pairing-invites", headers=HEADERS, json={"role": role}).json()
    claim = client.post("/v1/pairing/claim", json={"code": invite["code"]}).json()
    assert claim["linked"] is True
    body = client.get("/v1/devices", headers=HEADERS).json()
    return body["devices"][0]


def test_inventario_incluye_permisos_por_dispositivo(client: TestClient) -> None:
    body = client.get("/v1/devices", headers=HEADERS).json()
    settings = {item["source"]: item for item in body["settings"]}
    assert set(settings) == {"glasses", "phone", "portal", "backend"}
    assert settings["glasses"]["microphone"] is True
    assert settings["glasses"]["camera"] is True
    assert settings["portal"]["camera"] is False
    assert settings["backend"]["location"] is False
    assert body["settings"][0]["updated_at"] is None


def test_guarda_permisos_y_los_devuelve(client: TestClient) -> None:
    response = client.put(
        "/v1/devices/sources/glasses/settings", headers=HEADERS,
        json={"microphone": False, "camera": True, "location": False, "tracking": True},
    )
    assert response.status_code == 200
    settings = {item["source"]: item for item in response.json()["settings"]}
    assert settings["glasses"]["microphone"] is False
    assert settings["glasses"]["location"] is False
    assert settings["glasses"]["camera"] is True
    assert settings["glasses"]["updated_at"] is not None
    # Persiste entre peticiones.
    again = {item["source"]: item for item in client.get("/v1/devices", headers=HEADERS).json()["settings"]}
    assert again["glasses"]["microphone"] is False


def test_rechaza_dispositivo_desconocido_en_permisos(client: TestClient) -> None:
    response = client.put(
        "/v1/devices/sources/router/settings", headers=HEADERS,
        json={"microphone": True, "camera": True, "location": True, "tracking": True},
    )
    assert response.status_code == 422


def test_revoca_una_credencial_y_la_marca(client: TestClient) -> None:
    device = _pair(client, "caregiver")
    response = client.post(f"/v1/devices/{device['id']}/revoke", headers=HEADERS)
    assert response.status_code == 200
    revoked = [item for item in response.json()["devices"] if item["id"] == device["id"]][0]
    assert revoked["revoked"] is True
    assert client.post(f"/v1/devices/{device['id']}/revoke", headers=HEADERS).status_code == 404
    assert client.post("/v1/devices/no-existe/revoke", headers=HEADERS).status_code == 404


def test_prueba_de_conexion_de_una_fuente_con_actividad(client: TestClient) -> None:
    main.repository.add_event(main.EventCreate(kind="conversation", summary="hola", source="phone", severity="info"))
    result = client.post("/v1/devices/connection-test", headers=HEADERS, json={"device": "phone"}).json()
    assert result["online"] is True
    assert result["label"] == "Móvil"
    assert result["last_activity_at"] is not None
    assert result["latency_ms"] >= 1
    assert "evento" in result["detail"]


def test_prueba_de_conexion_de_la_camara_sin_imagen(client: TestClient) -> None:
    result = client.post("/v1/devices/connection-test", headers=HEADERS, json={"device": "camera"}).json()
    assert result["online"] is False
    assert "imágenes" in result["detail"].lower()


def test_prueba_de_conexion_de_la_camara_con_imagen_reciente(client: TestClient) -> None:
    main._LAST_CAMERA_FRAME["at"] = main.now()
    result = client.post("/v1/devices/connection-test", headers=HEADERS, json={"device": "camera"}).json()
    assert result["online"] is True
    assert result["last_activity_at"] is not None


def test_prueba_de_conexion_rechaza_dispositivo_desconocido(client: TestClient) -> None:
    response = client.post("/v1/devices/connection-test", headers=HEADERS, json={"device": "router"})
    assert response.status_code == 422


def test_puerta_de_dispositivos_redisenada_en_html() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    section_start = html.index('id="devices-view"')
    section = html[section_start : html.index("</section>", section_start)]
    assert "Dispositivos y servicios" in section
    assert 'id="device-summary"' in section
    assert 'id="devices"' in section
    assert 'id="device-pair"' in section
    assert 'id="devices-refresh"' in section
    assert 'id="pair-dialog"' in html
    assert 'id="device-pair-role"' in html


def test_js_agrupa_por_dispositivo_y_expone_acciones() -> None:
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in (
        "function renderDevices(inventory, liveViews, trackers)",
        "deviceSection('Dispositivos'",
        "deviceSection('Accesos autorizados'",
        "deviceSection('Privacidad y consentimiento'",
        "deviceSection('Transmisiones'",
        "deviceSection('Rastreadores'",
        "/v1/devices/sources/",
        "/revoke",
        "/v1/devices/connection-test",
        "Probar conexión",
        "Guardar permisos",
    ):
        assert marker in js
    assert "Dispositivo autorizado · ${device.role}" not in js


def test_css_responsive_y_tarjetas() -> None:
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    assert ".device-grid" in css
    assert ".device-status.is-offline" in css
    assert "grid-template-columns:1fr" in css
    assert "@media(max-width:720px)" in css


def test_dashboard_estado_de_faro_en_html() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    section_start = html.index('id="devices-view"')
    section = html[section_start : html.index("</section>", section_start)]
    assert 'id="device-health"' in section
    assert section.index('id="device-health"') < section.index('id="device-summary"')


def test_js_calcula_los_semaforos_del_estado_de_faro() -> None:
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    for marker in (
        "function renderHealth(",
        "renderHealth({inventory: devices, tracking, reviews, contacts, events})",
        "Batería",
        "Última conexión",
        "Estado de la cámara",
        "Calidad de conexión",
        "Última sincronización",
        "Errores de reconocimiento",
        "Estado de los avisos",
        "health-overall",
        "battery_percent",
    ):
        assert marker in js


def test_css_del_dashboard_y_responsive() -> None:
    css = (ROOT / "web" / "assets" / "app.css").read_text(encoding="utf-8")
    for marker in (
        ".health-grid",
        ".health-card--good",
        ".health-card--warn",
        ".health-card--bad",
        ".health-overall--bad",
    ):
        assert marker in css


def test_cache_del_service_worker_actualizada() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    sw = (ROOT / "web" / "assets" / "sw.js").read_text(encoding="utf-8")
    assert re.search(r"/assets/app\.js\?v=54", html)
    assert re.search(r"/assets/app\.css\?v=7", html)
    cache = re.search(r"faro-familia-v(\d+)", sw)
    assert cache and int(cache.group(1)) >= 63
    assert "/assets/app.js?v=54" in sw
    assert "/assets/app.css?v=7" in sw
