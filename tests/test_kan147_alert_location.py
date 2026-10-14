"""KAN-147 — el aviso adjunta la ultima ubicacion GPS recordada y la foto (regresion foto+ubicacion)."""

from __future__ import annotations

import base64
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-kan147-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    main.repository.care_contacts.clear()
    main.repository.emergency_alerts.clear()
    main.repository.last_emergency_at.clear()
    main._LAST_DEVICE_LOCATION.clear()
    return TestClient(main.app)


def _contact_and_capture(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[list, list]:
    contact = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Bibiana", "phone_e164": "+34644610954", "whatsapp_consent": True,
        "priority": 1, "alerts_enabled": True,
    })
    assert contact.status_code == 201, contact.text
    sent: list = []
    images: list = []

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        sent.append(alert)
        images.append(image)
        return [(contacts[0], main.AlertDelivery(message_id="wamid-kan147"))], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    return sent, images


def test_alert_reuses_recent_gps_location(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent, _ = _contact_and_capture(client, monkeypatch)
    located = client.post("/v1/location/answer", headers=HEADERS, json={
        "latitude": 42.2406, "longitude": -8.7207, "accuracy_meters": 18,
    })
    assert located.status_code == 200, located.text
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Faro, necesito ayuda", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["latitude"] == 42.2406
    assert response.json()["location_source"] == "gps"
    assert sent and sent[0].latitude == 42.2406
    assert "maps.google" in main.build_alert_message(sent[0])


def test_alert_without_recent_location_still_sends(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent, _ = _contact_and_capture(client, monkeypatch)
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Me caí", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["latitude"] is None


def test_stale_device_location_is_not_attached(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _contact_and_capture(client, monkeypatch)
    main._LAST_DEVICE_LOCATION.update({
        "latitude": 42.0, "longitude": -8.0, "accuracy_meters": 20,
        "recorded_at": main.now() - timedelta(minutes=30),
        "stored_at": main.now() - timedelta(minutes=30),
    })
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Ayuda", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    assert response.json()["latitude"] is None


def test_alert_keeps_photo_evidence(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, images = _contact_and_capture(client, monkeypatch)
    photo = base64.b64encode(b"\xff\xd8\xffdemo-jpeg-payload").decode()
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Ayuda con foto", "explicit_help_request": True,
        "evidence_image_base64": photo, "evidence_mime_type": "image/jpeg",
        "evidence_captured_at": main.now().isoformat(),
    })
    assert response.status_code == 201, response.text
    assert images and images[0] == b"\xff\xd8\xffdemo-jpeg-payload"
