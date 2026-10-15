"""KAN-151 - la imagen capturada en un aviso se guarda y se sirve (para verla en Memoria)."""

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

TOKEN = "integration-kan151-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setattr(main.repository, "alert_images_dir", tmp_path)
    main.repository.care_contacts.clear()
    main.repository.emergency_alerts.clear()
    main.repository.last_emergency_at.clear()

    def fake_send(contacts, alert, image=None):  # noqa: ANN001
        status = "sent" if image else "not_requested"
        return [(contacts[0], main.AlertDelivery(message_id="wamid-kan151", photo_status=status))], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)
    return TestClient(main.app)


def _make_contact(client: TestClient) -> None:
    response = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Bibiana", "phone_e164": "+34644610954", "whatsapp_consent": True,
        "priority": 1, "alerts_enabled": True,
    })
    assert response.status_code == 201, response.text


def test_alert_image_is_stored_and_served(client: TestClient) -> None:
    _make_contact(client)
    photo = b"\xff\xd8\xffdemo-kan151-jpeg"
    encoded = base64.b64encode(photo).decode()
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Ayuda con foto", "explicit_help_request": True,
        "evidence_image_base64": encoded, "evidence_mime_type": "image/jpeg",
        "evidence_captured_at": main.now().isoformat(),
    })
    assert response.status_code == 201, response.text
    alert_id = response.json()["id"]
    image = client.get(f"/v1/emergency-alerts/{alert_id}/image", headers=HEADERS)
    assert image.status_code == 200, image.text
    assert image.headers["content-type"] == "image/jpeg"
    assert image.content == photo
    events = client.get("/v1/events?limit=5", headers=HEADERS).json()
    matching = [event for event in events if (event.get("metadata") or {}).get("alert_id") == alert_id]
    assert matching and matching[0]["metadata"].get("has_photo") is True


def test_alert_without_image_returns_404(client: TestClient) -> None:
    _make_contact(client)
    response = client.post("/v1/emergency-alerts", headers=HEADERS, json={
        "kind": "episode", "spoken_message": "Sin foto", "explicit_help_request": True,
    })
    assert response.status_code == 201, response.text
    alert_id = response.json()["id"]
    image = client.get(f"/v1/emergency-alerts/{alert_id}/image", headers=HEADERS)
    assert image.status_code == 404
