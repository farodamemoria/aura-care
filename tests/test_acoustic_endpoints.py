"""KAN-35 — Pruebas de integración de los endpoints de escucha ambiental."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402
from app.environmental_listening import EnvironmentalListeningEngine, ListeningConfig  # noqa: E402

TOKEN = "integration-acoustic-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
DETECTION = {"signal": "cough", "confidence": 0.9}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.care_contacts.clear()
    main.repository.last_auto_alert.clear()
    main.acoustic_listening = EnvironmentalListeningEngine(ListeningConfig())
    return TestClient(main.app)


def configure_contact(client: TestClient) -> None:
    response = client.post("/v1/care-contacts", headers=HEADERS, json={
        "display_name": "Cuidadora", "phone_e164": "+34600111222", "role": "family",
        "whatsapp_consent": True, "priority": 1, "alerts_enabled": True,
    })
    assert response.status_code == 201, response.text


def cough(client: TestClient, times: int, occurred_at: str | None = None) -> dict:
    payload = dict(DETECTION)
    if occurred_at:
        payload["occurred_at"] = occurred_at
    response = None
    for _ in range(times):
        response = client.post("/v1/acoustic-events", headers=HEADERS, json=payload)
        assert response.status_code == 200, response.text
    return response.json()


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/acoustic-events", json=DETECTION).status_code == 401
    assert client.post("/v1/acoustic-events/response", json={"text": "ayuda"}).status_code == 401
    assert client.get("/v1/acoustic-episodes").status_code == 401


def test_isolated_cough_does_not_record_an_episode(client: TestClient) -> None:
    assert cough(client, 2)["action"] == "listening"
    assert client.get("/v1/acoustic-episodes", headers=HEADERS).json()["history"] == []


def test_repeated_cough_asks_and_records_a_check_in(client: TestClient) -> None:
    outcome = cough(client, 3)
    assert outcome["action"] == "ask"
    episodes = client.get("/v1/acoustic-episodes", headers=HEADERS).json()
    assert episodes["active"]["signal"] == "cough"
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "episode"}).json()
    assert any("Posible tos" in event["summary"] for event in events)


def test_reassuring_answer_stops_without_alerting(client: TestClient) -> None:
    configure_contact(client)
    cough(client, 3)
    outcome = client.post("/v1/acoustic-events/response", headers=HEADERS, json={"text": "Estoy bien, gracias"}).json()
    assert outcome["action"] == "closed"
    assert outcome["alerted"] is False
    history = client.get("/v1/acoustic-episodes", headers=HEADERS).json()["history"]
    assert history[0]["outcome"] == "reassured"


def test_help_request_escalates_to_the_care_network(client: TestClient) -> None:
    configure_contact(client)
    cough(client, 3)
    outcome = client.post("/v1/acoustic-events/response", headers=HEADERS, json={"text": "Ayuda, me duele el pecho"}).json()
    assert outcome["action"] == "escalate"
    assert outcome["alert"]["status"] in {"test_mode", "sent"}
    assert outcome["alert"]["recipients_attempted"] == 1
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "hazard"}).json()
    assert any("tos" in event["summary"].casefold() for event in events)


def test_escalation_without_contacts_reports_no_contact(client: TestClient) -> None:
    cough(client, 3)
    outcome = client.post("/v1/acoustic-events/response", headers=HEADERS, json={"text": "socorro"}).json()
    assert outcome["action"] == "escalate"
    assert outcome["alert"]["status"] == "no_contact"


def test_response_timeout_triggers_a_retry(client: TestClient) -> None:
    configure_contact(client)
    question_time = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
    cough(client, 3, occurred_at=question_time)
    retry = client.post("/v1/acoustic-events/tick", headers=HEADERS).json()
    assert retry["action"] == "ask" and retry["reason"] == "retry"
    assert retry["question"]
