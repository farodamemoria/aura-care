"""KAN-107 — Pruebas del generador inteligente de ejercicios cognitivos."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-generator-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository.memories.clear()
    main.repository.cognitive_exercises.clear()
    main.repository.people.clear()
    return TestClient(main.app)


def add_person(client: TestClient, name: str = "Bibiana", relacion: str = "hermana") -> None:
    response = client.post("/v1/people", headers=HEADERS, json={
        "display_name": name, "relationship": relacion, "consent_granted": True,
    })
    assert response.status_code == 201, response.text


def add_memory(client: TestClient, summary: str = "Le gustan las plantas del jardín") -> None:
    response = client.post("/v1/memories", headers=HEADERS, json={"kind": "care_note", "summary": summary})
    assert response.status_code == 201, response.text


def test_endpoint_requires_authentication(client: TestClient) -> None:
    assert client.post("/v1/cognitive-exercises/generate", json={"count": 3}).status_code == 401


def test_generates_from_family_and_memories(client: TestClient) -> None:
    add_person(client)
    add_memory(client)
    generated = client.post("/v1/cognitive-exercises/generate", headers=HEADERS, json={"count": 5})
    assert generated.status_code == 201, generated.text
    creados = generated.json()
    preguntas = {item["question"]: item for item in creados}
    assert "¿Cómo se llama tu hermana?" in preguntas
    assert preguntas["¿Cómo se llama tu hermana?"]["expected_answer"] == "Bibiana"
    assert any(item["category"] == "recall" for item in creados)


def test_does_not_duplicate(client: TestClient) -> None:
    add_person(client)
    client.post("/v1/cognitive-exercises/generate", headers=HEADERS, json={"count": 5})
    otra = client.post("/v1/cognitive-exercises/generate", headers=HEADERS, json={"count": 5}).json()
    assert otra == []


def test_respects_count(client: TestClient) -> None:
    add_person(client, "Bibiana", "hermana")
    add_person(client, "José", "hijo")
    add_memory(client)
    creados = client.post("/v1/cognitive-exercises/generate", headers=HEADERS, json={"count": 1}).json()
    assert len(creados) == 1
