"""KAN-75 Fase 2 - solicitud de transmision en directo, consentimiento y auditoria."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan75b-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
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


def _audit_events(action: str) -> list[main.Event]:
    return [
        event for event in main.repository.list_events(100, "caregiver_action")
        if (event.metadata or {}).get("action") == action
    ]


def test_consentimiento_requiere_auth_y_por_defecto_inactivo(client: TestClient) -> None:
    assert client.put("/v1/devices/video-consent", json={"granted": True}).status_code == 401
    body = client.get("/v1/devices", headers=HEADERS).json()
    assert body["video_consent"] is False


def test_activar_consentimiento_audita(client: TestClient) -> None:
    response = client.put(
        "/v1/devices/video-consent", headers=HEADERS, json={"granted": True, "notes": "prueba"}
    )
    assert response.status_code == 200
    assert response.json()["video_consent"] is True
    events = _audit_events("video_consent")
    assert len(events) == 1
    assert events[0].metadata.get("granted") is True


def test_solicitud_sin_consentimiento_rechazada(client: TestClient) -> None:
    response = client.post("/v1/live-views", headers=HEADERS, json={"source": "glasses"})
    assert response.status_code == 409


def test_ciclo_completo_de_transmision_auditado(client: TestClient) -> None:
    client.put("/v1/devices/video-consent", headers=HEADERS, json={"granted": True})
    created = client.post(
        "/v1/live-views", headers=HEADERS, json={"source": "phone", "reason": "demo"}
    ).json()
    assert created["status"] == "pending"
    listed = client.get("/v1/live-views", headers=HEADERS).json()
    assert [item["id"] for item in listed] == [created["id"]]
    active = client.post(
        f"/v1/live-views/{created['id']}/status", headers=HEADERS, json={"status": "active"}
    ).json()
    assert active["status"] == "active"
    done = client.post(
        f"/v1/live-views/{created['id']}/status", headers=HEADERS, json={"status": "completed"}
    ).json()
    assert done["status"] == "completed"
    assert len(_audit_events("live_view_request")) == 1
    assert len(_audit_events("live_view_status")) == 2


def test_cancelar_solicitud(client: TestClient) -> None:
    client.put("/v1/devices/video-consent", headers=HEADERS, json={"granted": True})
    created = client.post("/v1/live-views", headers=HEADERS, json={"source": "glasses"}).json()
    cancelled = client.post(
        f"/v1/live-views/{created['id']}/status", headers=HEADERS, json={"status": "cancelled"}
    ).json()
    assert cancelled["status"] == "cancelled"


def test_portal_tiene_controles_de_transmision() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "/v1/live-views" in js
    assert "/v1/devices/video-consent" in js
    assert "Solicitar transmisión" in js
    assert 'id="devices"' in html
