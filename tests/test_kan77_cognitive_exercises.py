"""KAN-77 — Casos de uso / pruebas de ejercicios cognitivos.

Cubren la generacion desde recuerdos verificados, las categorias, el registro
de resultados y el resumen de evolucion, ademas de la seccion del portal.
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

TOKEN = "integration-cognition-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
UNKNOWN = "00000000-0000-4000-8000-000000000000"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.memories.clear()
    main.repository.cognitive_exercises.clear()
    return TestClient(main.app)


def add_memory(client: TestClient, summary: str = "Le gustan las plantas del jardín") -> dict:
    response = client.post("/v1/memories", headers=HEADERS, json={"kind": "care_note", "summary": summary})
    assert response.status_code == 201, response.text
    return response.json()


def create_exercise(client: TestClient, memory_id: str, category: str | None = None) -> dict:
    payload = {"memory_id": memory_id}
    if category:
        payload["category"] = category
    response = client.post("/v1/cognitive-exercises", headers=HEADERS, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/v1/cognitive-exercises", json={"memory_id": UNKNOWN}).status_code == 401
    assert client.get("/v1/cognitive-exercises").status_code == 401
    assert client.get("/v1/cognitive-exercises/summary").status_code == 401


def test_exercise_is_built_from_a_verified_memory(client: TestClient) -> None:
    memory = add_memory(client)
    exercise = create_exercise(client, memory["id"])
    assert exercise["expected_answer"] == memory["summary"]
    assert memory["summary"] in exercise["question"]
    assert exercise["status"] == "pending"
    assert exercise["category"] == "recall"


def test_exercise_categories_change_the_question(client: TestClient) -> None:
    memory = add_memory(client)
    naming = create_exercise(client, memory["id"], "naming")
    assert naming["category"] == "naming"
    assert "Quién" in naming["question"]


def test_unknown_memory_is_rejected(client: TestClient) -> None:
    response = client.post("/v1/cognitive-exercises", headers=HEADERS, json={"memory_id": UNKNOWN})
    assert response.status_code == 404


def test_answering_records_result_and_summary(client: TestClient) -> None:
    memory = add_memory(client)
    first = create_exercise(client, memory["id"])
    second = create_exercise(client, memory["id"])
    client.post(f"/v1/cognitive-exercises/{first['id']}/answer", headers=HEADERS, json={"correct": True})
    answered = client.post(
        f"/v1/cognitive-exercises/{second['id']}/answer", headers=HEADERS, json={"correct": False},
    ).json()
    assert answered["status"] == "completed"
    assert answered["correct"] is False
    assert answered["answered_at"]
    summary = client.get("/v1/cognitive-exercises/summary", headers=HEADERS).json()
    assert summary == {"total": 2, "pending": 0, "completed": 2, "correct": 1, "accuracy": 50.0}
    events = client.get("/v1/events", headers=HEADERS, params={"kind": "routine"}).json()
    assert any("Ejercicio cognitivo" in event["summary"] for event in events)


def test_unknown_exercise_is_rejected(client: TestClient) -> None:
    response = client.post(f"/v1/cognitive-exercises/{UNKNOWN}/answer", headers=HEADERS, json={"correct": True})
    assert response.status_code == 404


def test_portal_has_the_exercises_section() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'data-view="exercises-view"' in html
    assert 'id="exercises"' in html
    script = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "/v1/cognitive-exercises" in script
