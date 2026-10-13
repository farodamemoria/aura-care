"""KAN-75 Fase 1 - inventario y estado de dispositivos del circulo de cuidado."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan75-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def test_inventario_requiere_autenticacion(client: TestClient) -> None:
    assert client.get("/v1/devices").status_code == 401


def test_inventario_lista_dispositivo_emparejado(client: TestClient) -> None:
    invite = client.post("/v1/pairing-invites", headers=HEADERS, json={"role": "family"}).json()
    claim = client.post("/v1/pairing/claim", json={"code": invite["code"]}).json()
    assert claim["linked"] is True
    body = client.get("/v1/devices", headers=HEADERS).json()
    assert len(body["devices"]) == 1
    device = body["devices"][0]
    assert device["role"] == "family"
    assert device["revoked"] is False
    assert body["video_consent"] is False


def test_inventario_muestra_actividad_por_canal(client: TestClient) -> None:
    main.repository.add_event(main.EventCreate(kind="conversation", summary="hola", source="phone", severity="info"))
    main.repository.add_event(main.EventCreate(kind="recognition", summary="cara", source="glasses", severity="info"))
    body = client.get("/v1/devices", headers=HEADERS).json()
    activity = {item["source"]: item for item in body["sources"]}
    assert activity["phone"]["events_24h"] == 1
    assert activity["glasses"]["events_24h"] == 1
    assert activity["portal"]["events_24h"] == 0
    assert activity["phone"]["last_event_at"] is not None


def test_consentimiento_de_video_por_defecto_inactivo(client: TestClient) -> None:
    body = client.get("/v1/devices", headers=HEADERS).json()
    assert body["video_consent"] is False
    assert body["updated_at"]


def test_portal_muestra_el_panel_de_dispositivos() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'id="devices"' in html
    assert 'id="device-count"' in html
    assert "/v1/devices" in js
    assert "renderDevices" in js
    assert "/assets/app.js?v=41" in html
