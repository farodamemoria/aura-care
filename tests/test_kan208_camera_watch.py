"""KAN-208 - Regresion: el ojo Tapo no avisa al caer al suelo.

Vigilancia periodica del ojo (patrulla activa) con ahorro de IA: solo se analiza
cuando la escena cambia, el presupuesto no bloquea la seguridad y un PELIGRO
(por ejemplo, una persona caida) avisa a la familia con foto.
"""

from __future__ import annotations

import base64
import datetime as dt
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan208-watch-token-4b7d2e9f1a3c5e8b0d2f4a6c8e1b3d5f"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"TAPO-C210-WATCH" * 40 + b"\xff\xd9"
JPEG_B64 = base64.b64encode(JPEG).decode()


def _reset_eye() -> None:
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
    with main._camera_watch_lock:
        main._camera_watch.update({
            "last_request_at": None, "last_request_id": None,
            "last_check_at": None, "last_check_result": None, "last_hazard_at": None,
        })


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVIDENCE_BUCKET", "")
    main.repository = main.InMemoryRepository()
    _reset_eye()
    return TestClient(main.app)


@pytest.fixture()
def alerts(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send(contacts, alert, image=None):
        calls.append({"contacts": contacts, "alert": alert, "image": image})
        return [(contacts[0], SimpleNamespace(message_id="msg-watch", photo_status="sent"))], []

    monkeypatch.setattr(main, "enabled_alert_contacts", lambda: [SimpleNamespace(id="contact-1")])
    monkeypatch.setattr(main, "active_alert_location", lambda: (None, None))
    monkeypatch.setattr(main, "recent_device_location", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    return calls


def _enable_patrol(client: TestClient, interval: int = 60) -> None:
    response = client.put(
        "/v1/camera/patrol", headers=HEADERS,
        json={"enabled": True, "interval_seconds": interval, "daily_budget": 1000},
    )
    assert response.status_code == 200


def _expire_watch_window() -> None:
    with main._camera_watch_lock:
        main._camera_watch["last_request_at"] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=3600)
        )


def test_watch_requests_a_photo_when_patrol_is_enabled(client: TestClient) -> None:
    assert client.get("/v1/camera/capture", headers=HEADERS).status_code == 204

    _enable_patrol(client, interval=60)
    first = client.get("/v1/camera/capture", headers=HEADERS)
    assert first.status_code == 200
    body = first.json()
    assert body["reason"] == "watch"
    assert body["request_id"].startswith("watch-")

    # La siguiente consulta inmediata no repite la captura (cadencia respetada).
    assert client.get("/v1/camera/capture", headers=HEADERS).status_code == 204

    _expire_watch_window()
    assert client.get("/v1/camera/capture", headers=HEADERS).json()["reason"] == "watch"

    status = client.get("/v1/camera/status", headers=HEADERS).json()
    assert status["patrol_enabled"] is True
    assert status["watch"]["enabled"] is True
    assert status["watch"]["interval_seconds"] == 60
    assert status["watch"]["next_check_at"]


def test_watch_does_not_analyze_an_unchanged_scene(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(image: str, mime: str) -> str:
        raise AssertionError("no se debe llamar a la IA si la escena no cambia")

    monkeypatch.setattr(main, "describe_camera_scene", boom)
    _enable_patrol(client)
    body = client.post(
        "/v1/camera/frame", headers=HEADERS,
        json={"image_base64": JPEG_B64, "reason": "watch", "changed": False},
    ).json()
    assert body["skipped"] == "no_change"
    assert body["hazard"] is False
    assert body["reason"] == "watch"
    status = client.get("/v1/camera/status", headers=HEADERS).json()
    assert status["online"] is True
    assert status["watch"]["last_check_at"]
    assert status["watch"]["last_result"]["skipped"] == "no_change"


def test_watch_fall_alerts_the_family_with_photo(
    client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main, "describe_camera_scene",
        lambda image, mime: "PELIGRO: una persona mayor caida en el suelo del salon.",
    )
    _enable_patrol(client)
    body = client.post(
        "/v1/camera/frame", headers=HEADERS,
        json={"image_base64": JPEG_B64, "reason": "watch", "changed": True},
    ).json()
    assert body["hazard"] is True
    assert body["kind"] == "dangerous_impact"
    assert body["family_alert_status"] == "sent"
    assert body["reason"] == "watch"
    assert len(alerts) == 1
    assert alerts[0]["image"] == JPEG
    assert alerts[0]["alert"].kind == "hazard"
    assert "caída o golpe" in alerts[0]["alert"].spoken_message
    events = client.get("/v1/events", headers=HEADERS).json()
    hazard = [event for event in events if event["kind"] == "hazard"]
    assert hazard and hazard[0]["metadata"]["camera"] == "tapo"
    assert hazard[0]["metadata"]["family_alert_status"] == "sent"
    reminders = client.get("/v1/voice-reminders", headers=HEADERS).json()
    assert any(item["kind"] == "hazard" for item in reminders)
    status = client.get("/v1/camera/status", headers=HEADERS).json()
    assert status["hazard"] is True
    assert status["watch"]["last_hazard_at"]


def test_watch_keeps_working_when_the_ai_budget_is_exhausted(
    client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main, "describe_camera_scene",
        lambda image, mime: "PELIGRO: una persona caida en el suelo.",
    )
    _enable_patrol(client)
    main.repository.event_db.execute(
        "INSERT OR REPLACE INTO configuration(key, value_json) VALUES('camera_usage', ?)",
        (main.json.dumps({
            "day": main.datetime.now(main.timezone.utc).date().isoformat(), "count": 99999,
        }),),
    )
    main.repository.event_db.commit()

    watch = client.post(
        "/v1/camera/frame", headers=HEADERS,
        json={"image_base64": JPEG_B64, "reason": "watch", "changed": True},
    ).json()
    assert watch["hazard"] is True
    assert watch["family_alert_status"] == "sent"
    assert watch.get("skipped") is None

    demand = client.post(
        "/v1/camera/frame", headers=HEADERS, json={"image_base64": JPEG_B64},
    ).json()
    assert demand["skipped"] == "budget"
    assert demand["hazard"] is False


def test_failed_alert_is_retried_on_the_next_watch_pass(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main, "describe_camera_scene",
        lambda image, mime: "PELIGRO: persona en el suelo.",
    )
    monkeypatch.setattr(main, "enabled_alert_contacts", lambda: [SimpleNamespace(id="contact-1")])
    monkeypatch.setattr(main, "active_alert_location", lambda: (None, None))
    monkeypatch.setattr(main, "recent_device_location", lambda *args, **kwargs: None)
    attempts: list = []

    def failing_send(contacts, alert, image=None):
        attempts.append(alert)
        return [], ["whatsapp caido"]

    monkeypatch.setattr(main, "send_alert_to_contacts", failing_send)
    _enable_patrol(client)
    first = client.post(
        "/v1/camera/frame", headers=HEADERS,
        json={"image_base64": JPEG_B64, "reason": "watch", "changed": True},
    ).json()
    assert first["family_alert_status"] == "failed"
    second = client.post(
        "/v1/camera/frame", headers=HEADERS,
        json={"image_base64": JPEG_B64, "reason": "watch", "changed": True},
    ).json()
    assert second["hazard"] is True
    assert len(attempts) == 2


def test_camera_hazard_kind_prefers_a_fall_over_a_door(client: TestClient) -> None:
    assert main.camera_hazard_kind(
        "PELIGRO: una persona caida en el suelo junto a la puerta abierta."
    ) == "dangerous_impact"
    assert main.camera_hazard_kind("PELIGRO: la puerta de casa abierta.") == "door_open"


def _load_bridge():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "camera_eye_bridge", ROOT / "scripts" / "camera_eye_bridge.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jpeg(color: int, box: tuple | None = None) -> bytes:
    import io

    from PIL import Image

    image = Image.new("L", (320, 240), color)
    if box:
        image.paste(255, box)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def test_bridge_detects_motion_and_ignores_a_static_scene() -> None:
    bridge = _load_bridge()
    quiet = _jpeg(60)
    same = _jpeg(60)
    fall = _jpeg(60, (40, 160, 260, 220))
    assert bridge.scene_changed(None, bridge.frame_signature(quiet), 4.0) is True
    assert bridge.scene_changed(
        bridge.frame_signature(quiet), bridge.frame_signature(same), 4.0,
    ) is False
    assert bridge.scene_changed(
        bridge.frame_signature(quiet), bridge.frame_signature(fall), 4.0,
    ) is True
    assert bridge.scene_changed(
        bridge.frame_signature(quiet), bridge.frame_signature(same), 0,
    ) is True
