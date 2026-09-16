"""KAN-108 — Pruebas de la evolucion de los ejercicios cognitivos (auditoria)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-evolution-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.memories.clear()
    main.repository.cognitive_exercises.clear()
    return TestClient(main.app)


def add_exercise(client: TestClient) -> str:
    memory = client.post("/v1/memories", headers=HEADERS, json={
        "kind": "care_note", "summary": "Le gustan las plantas del jardín",
    }).json()
    exercise = client.post("/v1/cognitive-exercises", headers=HEADERS, json={
        "memory_id": memory["id"],
    }).json()
    return exercise["id"]


def test_endpoint_requires_authentication(client: TestClient) -> None:
    assert client.get("/v1/cognitive-exercises/evolution").status_code == 401


def test_evolution_agrega_resultados(client: TestClient) -> None:
    primero = add_exercise(client)
    segundo = add_exercise(client)
    client.post(f"/v1/cognitive-exercises/{primero}/answer", headers=HEADERS, json={"correct": True})
    client.post(f"/v1/cognitive-exercises/{segundo}/answer", headers=HEADERS, json={"correct": False})
    datos = client.get("/v1/cognitive-exercises/evolution", headers=HEADERS).json()
    assert datos["total"] == 2
    assert datos["completed"] == 2
    assert datos["correct"] == 1
    assert datos["accuracy"] == 50.0
    assert datos["by_category"].get("recall") == 2
    assert len(datos["history"]) >= 1
    ultimo = datos["history"][-1]
    assert ultimo["total"] == 2 and ultimo["completed"] == 2 and ultimo["correct"] == 1


def test_evolution_sin_datos(client: TestClient) -> None:
    datos = client.get("/v1/cognitive-exercises/evolution", headers=HEADERS, params={"days": 7}).json()
    assert datos["days"] == 7
    assert datos["total"] == 0
    assert datos["accuracy"] == 0.0
    assert datos["history"] == []
