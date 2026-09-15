"""KAN-50 — Casos de uso / pruebas de la gestion de medicacion.

Cubren las pautas, la generacion de recordatorios y dosis por franja horaria,
la confirmacion del paciente, el escalado a la red de cuidados cuando no hay
confirmacion y la validacion de horarios.
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

TOKEN = "integration-medication-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
AT_0830 = "2026-09-15T08:30:00+02:00"
AT_0900 = "2026-09-15T09:00:00+02:00"
AT_1000 = "2026-09-15T10:00:00+02:00"
DAY = "2026-09-15"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.medication_plans.clear()
    main.repository.medication_doses.clear()
    main.repository.care_contacts.clear()
    main.repository.last_auto_alert.clear()
    return TestClient(main.app)


def create_plan(
    client: TestClient, medication: str = "Donepezilo", times: tuple[str, ...] = ("09:00", "21:00"),
) -> dict:
    response = client.post("/v1/medication-plans", headers=HEADERS, json={
        "medication": medication, "dose": "1 comprimido", "times": list(times),
    })
    assert response.status_code == 201, response.text
    return response.json()


def add_contact(client: TestClient) -> None:
    response = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Cuidadora", "phone_e164": "+34600111222", "role": "family",
        "whatsapp_consent": True, "priority": 1, "alerts_enabled": True,
    })
    assert response.status_code == 201, response.text


def tick(client: TestClient, at: str) -> dict:
    response = client.post("/v1/medication-tick", headers=HEADERS, params={"at": at})
    assert response.status_code == 200, response.text
    return response.json()


def doses(client: TestClient) -> list[dict]:
    return client.get("/v1/medication-doses", headers=HEADERS, params={"day": DAY}).json()


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/medication-plans", json={"medication": "x", "times": ["09:00"]}).status_code == 401
    assert client.get("/v1/medication-plans").status_code == 401
    assert client.get("/v1/medication-doses").status_code == 401
    assert client.post("/v1/medication-tick").status_code == 401


def test_plan_crud(client: TestClient) -> None:
    plan = create_plan(client)
    assert plan["medication"] == "Donepezilo"
    assert client.get("/v1/medication-plans", headers=HEADERS).json()[0]["id"] == plan["id"]
    patched = client.patch(
        f"/v1/medication-plans/{plan['id']}", headers=HEADERS, json={"enabled": False},
    ).json()
    assert patched["enabled"] is False
    assert client.delete(f"/v1/medication-plans/{plan['id']}", headers=HEADERS).status_code == 204
    assert client.get("/v1/medication-plans", headers=HEADERS).json() == []


def test_invalid_time_is_rejected(client: TestClient) -> None:
    assert client.post(
        "/v1/medication-plans", headers=HEADERS, json={"medication": "x", "times": ["25:00"]},
    ).status_code == 422
    plan = create_plan(client)
    assert client.patch(
        f"/v1/medication-plans/{plan['id']}", headers=HEADERS, json={"times": ["9:00"]},
    ).status_code == 422


def test_tick_creates_reminder_and_dose(client: TestClient) -> None:
    create_plan(client)
    assert tick(client, AT_0830)["reminders"] == []
    result = tick(client, AT_0900)
    assert len(result["reminders"]) == 1
    assert "Donepezilo" in result["reminders"][0]["message"]
    assert [dose["status"] for dose in doses(client)] == ["pending"]
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "routine"}).json()
    assert any("Recordatorio de medicación" in event["summary"] for event in events)


def test_tick_does_not_duplicate_reminders(client: TestClient) -> None:
    create_plan(client)
    tick(client, AT_0900)
    assert tick(client, AT_0900)["reminders"] == []
    assert len(doses(client)) == 1


def test_confirm_dose_records_the_taken_state(client: TestClient) -> None:
    create_plan(client)
    tick(client, AT_0900)
    dose = doses(client)[0]
    confirmed = client.post(f"/v1/medication-doses/{dose['id']}/confirm", headers=HEADERS).json()
    assert confirmed["status"] == "taken"
    assert confirmed["confirmed_at"]
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "routine"}).json()
    assert any("Medicación confirmada" in event["summary"] for event in events)


def test_overdue_dose_escalates_to_the_care_network(client: TestClient) -> None:
    create_plan(client)
    add_contact(client)
    tick(client, AT_0900)
    result = tick(client, AT_1000)
    assert len(result["escalations"]) == 1
    assert result["escalations"][0]["family_alert_status"] in {"sent", "test_mode"}
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "hazard"}).json()
    assert any("medicación" in event["summary"] for event in events)


def test_escalation_without_contacts_reports_no_contact(client: TestClient) -> None:
    create_plan(client)
    tick(client, AT_0900)
    result = tick(client, AT_1000)
    assert result["escalations"][0]["family_alert_status"] == "no_contact"


def test_escalation_happens_only_once(client: TestClient) -> None:
    create_plan(client)
    add_contact(client)
    tick(client, AT_0900)
    tick(client, AT_1000)
    assert tick(client, AT_1000)["escalations"] == []


def test_disabled_plan_does_not_remind(client: TestClient) -> None:
    plan = create_plan(client)
    client.patch(f"/v1/medication-plans/{plan['id']}", headers=HEADERS, json={"enabled": False})
    assert tick(client, AT_0900)["reminders"] == []


def test_unknown_dose_confirmation_is_rejected(client: TestClient) -> None:
    unknown = "00000000-0000-4000-8000-000000000000"
    assert client.post(f"/v1/medication-doses/{unknown}/confirm", headers=HEADERS).status_code == 404
