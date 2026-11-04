"""KAN-206: el chat familiar responde parentescos aunque no haya clave de IA."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan206-token-6a4f0c2d8e1b7935a5d6e7f8091b2c3d"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.delenv("AURA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    main.repository = main.InMemoryRepository()
    for name, relationship in (
        ("Bibiana", "mujer y esposa"),
        ("Sasha Zuklevicius", "Hija"),
        ("Ellah SÃ¡nchez", "hija de tu amigo Jose MarÃ­a"),
        ("Jose", "Cuidador"),
    ):
        person = main.Person(
            id=main.uuid4(), display_name=name, relationship=relationship,
            consent_granted=True, created_at=main.now(),
        )
        main.repository.people[person.id] = person
    return TestClient(main.app)


def test_relationship_lookup_returns_wife(client: TestClient) -> None:
    assert main.people_lookup_answer("Â¿CÃ³mo se llama mi mujer?", "es") == \
        "Bibiana es tu mujer y esposa."


def test_relationship_lookup_prefers_exact_relationship(client: TestClient) -> None:
    answer = main.people_lookup_answer("Â¿CÃ³mo se llama mi hija?", "es")
    assert answer == "Sasha Zuklevicius es tu Hija."


def test_relationship_lookup_by_name(client: TestClient) -> None:
    assert main.people_lookup_answer("Â¿QuiÃ©n es Jose?", "es") == "Jose es tu Cuidador."


def test_relationship_lookup_ignores_unrelated_question(client: TestClient) -> None:
    assert main.people_lookup_answer("Â¿QuÃ© pasÃ³ ayer por la tarde?", "es") is None


def test_family_ask_answers_relationship_without_ai_key(client: TestClient) -> None:
    response = client.post(
        "/v1/family/ask",
        json={"question": "Â¿CÃ³mo se llama mi mujer?", "language": "es"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["generated_by"] == "summary"
    assert "Bibiana" in body["answer"]

