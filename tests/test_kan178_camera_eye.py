"""KAN-178 - Ojo de Faro: preview, captura bajo demanda y reconocimiento de la camara."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan178-eye-token-7a1c3e5d9b2f4c6a8e0d1b3f5c7a9e2d"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"TAPO-C210-FRAME" * 30 + b"\xff\xd9"
JPEG_B64 = base64.b64encode(JPEG).decode()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVIDENCE_BUCKET", "")
    main.repository = main.InMemoryRepository()
    main._camera_hazard_last.clear()
    main._LAST_CAMERA_FRAME["at"] = None
    with main._camera_eye_lock:
        main._camera_eye.update({
            "image": None, "mime_type": "image/jpeg", "captured_at": None,
            "description": None, "hazard": False, "kind": None,
            "evidence_key": None, "request_id": None,
        })
        main._camera_capture.update({
            "request_id": None, "requested_at": None, "fulfilled_at": None,
        })
    return TestClient(main.app)


@pytest.fixture()
def alerts(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send(contacts, alert, image=None):
        calls.append({"contacts": contacts, "alert": alert, "image": image})
        return [(contacts[0], SimpleNamespace(message_id="msg-eye", photo_status="sent"))], []

    monkeypatch.setattr(main, "enabled_alert_contacts", lambda: [SimpleNamespace(id="contact-1")])
    monkeypatch.setattr(main, "active_alert_location", lambda: (None, None))
    monkeypatch.setattr(main, "recent_device_location", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    return calls


def test_frame_upload_stores_preview_and_recognition(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main, "describe_camera_scene",
        lambda image, mime: "OK: una persona mayor sentada en el sofa del salon.",
    )
    response = client.post(
        "/v1/camera/frame", headers=HEADERS,
        json={"image_base64": JPEG_B64, "mime_type": "image/jpeg"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["hazard"] is False
    assert body["description"] == "una persona mayor sentada en el sofa del salon."
    assert body["captured_at"]

    preview = client.get("/v1/camera/preview", headers=HEADERS)
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.content == JPEG

    status = client.get("/v1/camera/status", headers=HEADERS).json()
    assert status["has_preview"] is True
    assert status["online"] is True
    assert status["description"] == "una persona mayor sentada en el sofa del salon."
    assert status["hazard"] is False


def test_capture_is_on_demand_and_fulfilled_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_scene", lambda image, mime: "OK: pasillo vacio.")
    assert client.get("/v1/camera/capture", headers=HEADERS).status_code == 204
    requested = client.post("/v1/camera/capture", headers=HEADERS, json={"note": "mirar el salon"})
    assert requested.status_code == 202
    request_id = requested.json()["request_id"]
    assert request_id

    pending = client.get("/v1/camera/capture", headers=HEADERS)
    assert pending.status_code == 200
    assert pending.json()["request_id"] == request_id

    upload = client.post(
        "/v1/camera/frame", headers=HEADERS,
        json={"image_base64": JPEG_B64, "request_id": request_id},
    )
    assert upload.status_code == 200
    assert client.get("/v1/camera/capture", headers=HEADERS).status_code == 204

    status = client.get("/v1/camera/status", headers=HEADERS).json()
    assert status["pending_capture"] is None


def test_hazard_from_the_eye_alerts_the_family(
    client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main, "describe_camera_scene",
        lambda image, mime: "PELIGRO: hay humo y fuego en la cocina.",
    )
    body = client.post(
        "/v1/camera/frame", headers=HEADERS, json={"image_base64": JPEG_B64},
    ).json()
    assert body["hazard"] is True
    assert body["kind"] == "smoke_or_fire"
    assert body["family_alert_status"] == "sent"
    assert body["spoken"]
    assert len(alerts) == 1 and alerts[0]["image"] == JPEG
    events = client.get("/v1/events", headers=HEADERS).json()
    assert any(event["kind"] == "hazard" for event in events)
    reminders = client.get("/v1/voice-reminders", headers=HEADERS).json()
    assert any(item["kind"] == "hazard" for item in reminders)
    status = client.get("/v1/camera/status", headers=HEADERS).json()
    assert status["hazard"] is True and status["kind"] == "smoke_or_fire"


def test_eye_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/camera/frame", json={"image_base64": JPEG_B64}).status_code == 401
    assert client.get("/v1/camera/status").status_code == 401
    assert client.get("/v1/camera/preview").status_code == 401
    assert client.post("/v1/camera/capture", json={}).status_code == 401
    assert client.get("/v1/camera/capture").status_code == 401


def test_preview_404_without_frames(client: TestClient) -> None:
    assert client.get("/v1/camera/preview", headers=HEADERS).status_code == 404


def test_budget_pause_keeps_the_preview(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(main.os.environ, "AURA_EVIDENCE_BUCKET", "")
    main.repository.event_db.execute(
        "INSERT OR REPLACE INTO configuration(key, value_json) VALUES('camera_usage', ?)",
        (main.json.dumps({"day": main.datetime.now(main.timezone.utc).date().isoformat(), "count": 99999}),),
    )
    main.repository.event_db.commit()
    body = client.post(
        "/v1/camera/frame", headers=HEADERS, json={"image_base64": JPEG_B64},
    ).json()
    assert body["skipped"] == "budget"
    assert body["hazard"] is False
    assert client.get("/v1/camera/preview", headers=HEADERS).content == JPEG
