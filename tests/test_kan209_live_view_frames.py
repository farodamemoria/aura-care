"""KAN-209 - regresion: el directo de gafas/movil no llega al portal.

Cubre el contrato que faltaba: la app consulta las solicitudes pendientes de su fuente,
sube fotogramas reales y el portal los descarga; al cerrar la solicitud se borra el
ultimo fotograma y queda auditoria en el evento.
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

TOKEN = "kan209-token-7c1f9a2b6d4e8035a5c7e9b1d3f62a"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"faro-live-frame" * 20 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"faro-live-frame" * 20


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    monkeypatch.setenv("AURA_LIVE_VIEW_DIR", str(tmp_path / "live-view-frames"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _pair(client: TestClient, role: str = "family") -> str:
    invite = client.post("/v1/pairing-invites", headers=HEADERS, json={"role": role}).json()
    claim = client.post("/v1/pairing/claim", json={"code": invite["code"]}).json()
    assert claim["linked"] is True
    return claim["device_credential"]


def _device_headers(token: str, source: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Faro-Device-Source": source}


def _enable_consent(client: TestClient) -> None:
    response = client.put("/v1/devices/video-consent", headers=HEADERS, json={"granted": True})
    assert response.status_code == 200


def _create(client: TestClient, source: str) -> dict:
    response = client.post("/v1/live-views", headers=HEADERS, json={"source": source})
    assert response.status_code == 201
    return response.json()


def _audit(action: str) -> list[main.Event]:
    return [
        event for event in main.repository.list_events(100, "caregiver_action")
        if (event.metadata or {}).get("action") == action
    ]


def test_la_app_encuentra_la_solicitud_pendiente_de_su_fuente(client: TestClient) -> None:
    _enable_consent(client)
    glasses = _create(client, "glasses")
    phone = _create(client, "phone")
    device = _pair(client)
    pending = client.get(
        "/v1/live-views?status=pending&source=glasses",
        headers=_device_headers(device, "glasses"),
    )
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()] == [glasses["id"]]
    everything = client.get("/v1/live-views", headers=HEADERS).json()
    assert {item["id"] for item in everything} == {glasses["id"], phone["id"]}
    assert all(item["frame_count"] == 0 for item in everything)


def test_la_app_sube_un_jpeg_y_el_portal_lo_ve(client: TestClient) -> None:
    _enable_consent(client)
    view = _create(client, "glasses")
    device = _pair(client)
    upload = client.post(
        f"/v1/live-views/{view['id']}/frame",
        headers={**_device_headers(device, "glasses"), "Content-Type": "image/jpeg"},
        content=JPEG,
    )
    assert upload.status_code == 202
    ack = upload.json()
    assert ack["status"] == "active"
    assert ack["frame_count"] == 1
    assert ack["received_bytes"] == len(JPEG)

    listed = client.get("/v1/live-views", headers=HEADERS).json()
    assert listed[0]["status"] == "active"
    assert listed[0]["frame_count"] == 1
    assert listed[0]["last_frame_at"]

    frame = client.get(f"/v1/live-views/{view['id']}/frame", headers=HEADERS)
    assert frame.status_code == 200
    assert frame.headers["content-type"].startswith("image/jpeg")
    assert frame.headers["cache-control"] == "no-store, private"
    assert frame.content == JPEG
    assert len(_audit("live_view_status")) == 1
    assert _audit("live_view_status")[0].metadata["trigger"] == "first_frame"


def test_png_con_contenido_por_defecto_tambien_se_acepta(client: TestClient) -> None:
    _enable_consent(client)
    view = _create(client, "phone")
    device = _pair(client)
    upload = client.post(
        f"/v1/live-views/{view['id']}/frame",
        headers={**_device_headers(device, "phone"), "Content-Type": "application/octet-stream"},
        content=PNG,
    )
    assert upload.status_code == 202
    frame = client.get(f"/v1/live-views/{view['id']}/frame", headers=HEADERS)
    assert frame.headers["content-type"].startswith("image/png")
    assert frame.content == PNG


def test_rechaza_fotograma_vacio_que_no_es_imagen_o_demasiado_grande(client: TestClient) -> None:
    _enable_consent(client)
    view = _create(client, "phone")
    device = _pair(client)
    url = f"/v1/live-views/{view['id']}/frame"
    headers = {**_device_headers(device, "phone"), "Content-Type": "image/jpeg"}
    assert client.post(url, headers=headers, content=b"").status_code == 422
    assert client.post(url, headers=headers, content=b"no soy una imagen").status_code == 415
    oversized = b"\xff\xd8\xff" + b"\x00" * (main.LIVE_VIEW_FRAME_MAX_BYTES + 1)
    assert client.post(url, headers=headers, content=oversized).status_code == 413


def test_una_app_no_puede_subir_a_la_solicitud_de_otra_fuente(client: TestClient) -> None:
    _enable_consent(client)
    view = _create(client, "glasses")
    device = _pair(client)
    response = client.post(
        f"/v1/live-views/{view['id']}/frame",
        headers={**_device_headers(device, "phone"), "Content-Type": "image/jpeg"},
        content=JPEG,
    )
    assert response.status_code == 403


def test_sin_credencial_no_se_puede_ni_listar_ni_subir(client: TestClient) -> None:
    _enable_consent(client)
    view = _create(client, "glasses")
    assert client.get("/v1/live-views").status_code == 401
    assert client.post(
        f"/v1/live-views/{view['id']}/frame",
        headers={"Content-Type": "image/jpeg"}, content=JPEG,
    ).status_code == 401
    assert client.get(f"/v1/live-views/{view['id']}/frame").status_code == 401


def test_al_cerrar_se_borra_el_fotograma_y_ya_no_se_aceptan_mas(client: TestClient) -> None:
    _enable_consent(client)
    view = _create(client, "phone")
    device = _pair(client)
    url = f"/v1/live-views/{view['id']}/frame"
    headers = {**_device_headers(device, "phone"), "Content-Type": "image/jpeg"}
    assert client.post(url, headers=headers, content=JPEG).status_code == 202
    closed = client.post(
        f"/v1/live-views/{view['id']}/status",
        headers=_device_headers(device, "phone"), json={"status": "completed"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "completed"
    assert client.get(f"/v1/live-views/{view['id']}/frame", headers=HEADERS).status_code == 404
    assert client.post(url, headers=headers, content=JPEG).status_code == 409
    assert not (main.repository.live_view_frames_dir / f"{view['id']}.jpg").exists()


def test_el_portal_puede_cerrar_la_transmision(client: TestClient) -> None:
    _enable_consent(client)
    view = _create(client, "glasses")
    response = client.post(
        f"/v1/live-views/{view['id']}/status", headers=HEADERS, json={"status": "cancelled"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_el_portal_tiene_visor_de_directo_con_polling_de_fotogramas() -> None:
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "/frame" in js
    assert "renderLiveView" in js or "liveViewViewer" in js
    assert 'id="live-view"' in html
