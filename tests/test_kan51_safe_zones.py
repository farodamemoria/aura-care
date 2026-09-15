"""KAN-51 — Casos de uso / pruebas de zonas seguras y geocercas.

Cubren el CRUD de zonas, la evaluacion dentro/fuera con margen de precision y
el escalado unico a la red de cuidados cuando la persona sale de sus zonas.
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

TOKEN = "integration-safezone-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

ZONE = {"name": "Casa", "latitude": 42.2406, "longitude": -8.7207, "radius_meters": 150.0}
INSIDE = {"latitude": 42.2407, "longitude": -8.7207, "accuracy_meters": 15.0}
FAR = {"latitude": 42.3000, "longitude": -8.7207, "accuracy_meters": 20.0}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.safe_zones.clear()
    main.repository.care_contacts.clear()
    main.repository.last_auto_alert.clear()
    return TestClient(main.app)


def create_zone(client: TestClient) -> dict:
    response = client.post("/v1/safe-zones", headers=HEADERS, json=ZONE)
    assert response.status_code == 201, response.text
    return response.json()


def add_contact(client: TestClient) -> None:
    response = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Cuidadora", "phone_e164": "+34600111222", "role": "family",
        "whatsapp_consent": True, "priority": 1, "alerts_enabled": True,
    })
    assert response.status_code == 201, response.text


def check(client: TestClient, point: dict) -> dict:
    response = client.post("/v1/safe-zones/check", headers=HEADERS, json=point)
    assert response.status_code == 200, response.text
    return response.json()


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/safe-zones", json=ZONE).status_code == 401
    assert client.get("/v1/safe-zones").status_code == 401
    assert client.post("/v1/safe-zones/check", json=FAR).status_code == 401


def test_zone_crud(client: TestClient) -> None:
    zone = create_zone(client)
    assert zone["name"] == "Casa"
    assert client.get("/v1/safe-zones", headers=HEADERS).json()[0]["id"] == zone["id"]
    patched = client.patch(
        f"/v1/safe-zones/{zone['id']}", headers=HEADERS, json={"radius_meters": 300.0},
    ).json()
    assert patched["radius_meters"] == 300.0
    assert client.delete(f"/v1/safe-zones/{zone['id']}", headers=HEADERS).status_code == 204
    assert client.get("/v1/safe-zones", headers=HEADERS).json() == []


def test_invalid_zone_is_rejected(client: TestClient) -> None:
    assert client.post(
        "/v1/safe-zones", headers=HEADERS, json={**ZONE, "radius_meters": 0},
    ).status_code == 422


def test_without_zones_reports_no_zones(client: TestClient) -> None:
    assert check(client, FAR)["status"] == "no_zones"


def test_point_inside_the_zone_is_ok(client: TestClient) -> None:
    create_zone(client)
    status = check(client, INSIDE)
    assert status["status"] == "inside"
    assert status["family_alert_status"] is None


def test_leaving_the_zone_alerts_once(client: TestClient) -> None:
    create_zone(client)
    add_contact(client)
    first = check(client, FAR)
    assert first["status"] == "outside"
    assert first["family_alert_status"] in {"sent", "test_mode"}
    assert first["distance_meters"] > ZONE["radius_meters"]
    assert check(client, FAR)["family_alert_status"] is None
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "location"}).json()
    assert any("zonas seguras" in event["summary"] for event in events)


def test_outside_without_contacts_reports_no_contact(client: TestClient) -> None:
    create_zone(client)
    assert check(client, FAR)["family_alert_status"] == "no_contact"


def test_disabled_zone_is_ignored(client: TestClient) -> None:
    zone = create_zone(client)
    client.patch(f"/v1/safe-zones/{zone['id']}", headers=HEADERS, json={"enabled": False})
    assert check(client, FAR)["status"] == "no_zones"
