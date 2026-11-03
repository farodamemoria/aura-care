"""KAN-178 - Ojo Tapo: deteccion de peligros y aviso urgente a la familia."""

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

TOKEN = "kan178-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG_B64 = base64.b64encode(b"\xff\xd8\xff\xe0" + b"TAPO-FRAME" * 20 + b"\xff\xd9").decode()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    main.repository = main.InMemoryRepository()
    main._camera_hazard_last.clear()
    return TestClient(main.app)


@pytest.fixture()
def alerts(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send(contacts, alert, image=None):
        calls.append({"contacts": contacts, "alert": alert, "image": image})
        return [(contacts[0], SimpleNamespace(message_id="msg-1", photo_status="sent"))], []

    monkeypatch.setattr(main, "enabled_alert_contacts", lambda: [SimpleNamespace(id="contact-1")])
    monkeypatch.setattr(main, "active_alert_location", lambda: (None, None))
    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    return calls


def test_hazard_sends_family_alert(client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_hazard", lambda image, mime: "PELIGRO: una persona caida en el suelo")
    response = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": JPEG_B64})
    assert response.status_code == 200
    body = response.json()
    assert body["hazard"] is True
    assert body["kind"] == "dangerous_impact"
    assert body["family_alert_status"] == "sent"
    assert body["photo_delivery_status"] == "sent"
    assert len(alerts) == 1
    assert alerts[0]["image"] is not None
    events = client.get("/v1/events", headers=HEADERS).json()
    assert any(event["kind"] == "hazard" for event in events)


def test_fire_hazard_kind(client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_hazard", lambda image, mime: "PELIGRO: humo y fuego en la cocina")
    body = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": JPEG_B64}).json()
    assert body["kind"] == "smoke_or_fire"
    assert len(alerts) == 1


def test_hazard_is_spoken_through_the_session(client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_hazard", lambda image, mime: "PELIGRO: persona caida en el suelo")
    body = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": JPEG_B64}).json()
    assert body["hazard"] is True
    assert "encuentras bien" in body["spoken"]
    reminders = client.get("/v1/voice-reminders", headers=HEADERS).json()
    assert any(item["kind"] == "hazard" and "encuentras bien" in item["message"] for item in reminders)

def test_door_open_kind_and_speech(client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_hazard", lambda image, mime: "PELIGRO: puerta de casa abierta")
    body = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": JPEG_B64}).json()
    assert body["kind"] == "door_open"
    assert "puerta" in body["spoken"].lower()
    assert len(alerts) == 1

def test_no_hazard_does_not_alert(client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_hazard", lambda image, mime: "OK: sala de estar sin peligros")
    body = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": JPEG_B64}).json()
    assert body["hazard"] is False
    assert body["family_alert_status"] is None
    assert alerts == []


def test_repeated_hazard_is_deduped(client: TestClient, alerts: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_hazard", lambda image, mime: "PELIGRO: persona en el suelo")
    first = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": JPEG_B64}).json()
    second = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": JPEG_B64}).json()
    assert first["family_alert_status"] == "sent"
    assert second["family_alert_status"] == "dedup"
    assert len(alerts) == 1


def test_invalid_image_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "describe_camera_hazard", lambda image, mime: "OK")
    response = client.post("/v1/camera-hazard", headers=HEADERS, json={"image_base64": "no-base64!!"})
    assert response.status_code == 422


def test_auth_required(client: TestClient) -> None:
    response = client.post("/v1/camera-hazard", json={"image_base64": JPEG_B64})
    assert response.status_code == 401
