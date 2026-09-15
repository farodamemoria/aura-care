"""KAN-40 — Casos de uso / pruebas de la memoria visual de objetos.

Cubren el registro de avistamientos, la consulta («¿dónde están las llaves?»),
la respuesta por chat cuando la IA no está disponible, la linea de tiempo del
portal y la validación de datos.
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

TOKEN = "integration-objects-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    monkeypatch.delenv("AURA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    main.repository.object_memories.clear()
    return TestClient(main.app)


def sighting(
    client: TestClient,
    object_name: str = "llaves",
    place: str = "mesilla del salón",
    seen_at: str | None = None,
    confidence: float = 0.92,
) -> dict:
    payload = {
        "object_name": object_name,
        "place": place,
        "confidence": confidence,
        "source": "glasses",
    }
    if seen_at:
        payload["seen_at"] = seen_at
    response = client.post("/v1/object-memories", headers=HEADERS, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/object-memories", json={"object_name": "llaves"}).status_code == 401
    assert client.get("/v1/object-memories").status_code == 401
    assert client.get("/v1/object-memories/last", params={"name": "llaves"}).status_code == 401


def test_sighting_is_recorded_and_appears_in_the_timeline(client: TestClient) -> None:
    created = sighting(client)
    assert created["object_name"] == "llaves"
    assert created["place"] == "mesilla del salón"
    assert created["seen_at"]
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "object_location"}).json()
    assert any("mesilla del salón" in event["summary"] for event in events)


def test_lookup_returns_the_most_recent_place(client: TestClient) -> None:
    sighting(client, place="cocina", seen_at="2026-09-10T09:00:00+00:00")
    sighting(client, place="mesilla del salón", seen_at="2026-09-15T18:30:00+00:00")
    matches = client.get("/v1/object-memories", headers=HEADERS, params={"name": "llaves"}).json()
    assert [item["place"] for item in matches] == ["mesilla del salón", "cocina"]
    last = client.get("/v1/object-memories/last", headers=HEADERS, params={"name": "llaves"}).json()
    assert last["place"] == "mesilla del salón"


def test_lookup_ignores_other_objects(client: TestClient) -> None:
    sighting(client, object_name="llaves", place="cocina")
    sighting(client, object_name="mando", place="salón")
    matches = client.get("/v1/object-memories", headers=HEADERS, params={"name": "llaves"}).json()
    assert [item["object_name"] for item in matches] == ["llaves"]
    assert client.get("/v1/object-memories/last", headers=HEADERS, params={"name": "gafas"}).json() is None


def test_validation_rejects_invalid_sightings(client: TestClient) -> None:
    assert client.post("/v1/object-memories", headers=HEADERS, json={"object_name": ""}).status_code == 422
    invalid = client.post(
        "/v1/object-memories", headers=HEADERS,
        json={"object_name": "llaves", "confidence": 1.5},
    )
    assert invalid.status_code == 422


def test_family_chat_answers_where_an_object_is(client: TestClient) -> None:
    sighting(client, object_name="llaves", place="mesilla del salón")
    answer = client.post(
        "/v1/family/ask", headers=HEADERS, json={"question": "¿Dónde están las llaves?"},
    ).json()
    assert "mesilla del salón" in answer["answer"]
    assert answer["generated_by"] == "summary"


def test_family_chat_ignores_unknown_objects(client: TestClient) -> None:
    answer = client.post(
        "/v1/family/ask", headers=HEADERS, json={"question": "¿Dónde están las gafas?"},
    ).json()
    assert "mesilla" not in answer["answer"]


def test_lookup_is_accent_and_case_insensitive(client: TestClient) -> None:
    sighting(client, object_name="Llaves", place="cocina")
    last = client.get("/v1/object-memories/last", headers=HEADERS, params={"name": "LLAVÉS"}).json()
    assert last["place"] == "cocina"
