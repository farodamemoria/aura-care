"""KAN-33 - memoria conversacional recuperable: busqueda, no alucinacion, deduplicacion y reinicio."""

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

TOKEN = "kan33-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _add(summary: str, speaker: str = "patient", minutes_ago: int = 0) -> None:
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    main.repository.add_event(main.EventCreate(
        kind="conversation", summary=summary, source="glasses", severity="info",
        occurred_at=when, metadata={"speaker": speaker, "transcript": True},
    ))


def _search(client: TestClient, query: str, limit: int = 8) -> list[dict]:
    response = client.get(
        "/v1/conversation-memory/search", params={"query": query, "limit": limit}, headers=HEADERS,
    )
    assert response.status_code == 200
    return response.json()


def test_recupera_conversacion_anterior(client: TestClient) -> None:
    _add("Ayer hablamos de la receta de la tarta de manzana")
    data = _search(client, "tarta")
    assert len(data) == 1
    assert "tarta" in data[0]["summary"]
    assert data[0]["event_id"]
    assert data[0]["relevance"] > 0


def test_sin_coincidencias_no_inventa(client: TestClient) -> None:
    _add("Hablamos del tiempo y de la compra")
    assert _search(client, "astronauta") == []


def test_descarta_transcripciones_artefacto(client: TestClient) -> None:
    _add("Faro da memoria nombres familiares ayuda perdido familia")
    _add("Conversacion real sobre la cena de cumpleanos")
    data = _search(client, "familia")
    assert all("Faro da memoria" not in item["summary"] for item in data)


def test_coincidencia_exacta_rankea_primero(client: TestClient) -> None:
    _add("hablamos de la compra semanal")
    _add("compromiso de llamar al medico")
    data = _search(client, "compromiso")
    assert data[0]["summary"].startswith("compromiso")


def test_deduplica_repeticiones(client: TestClient) -> None:
    _add("Tengo una revision medica el martes", minutes_ago=5)
    _add("Tengo una revision medica el martes", minutes_ago=1)
    data = _search(client, "revision")
    assert len(data) == 1


def test_sobrevive_al_reinicio_de_sesion(client: TestClient) -> None:
    _add("Guardamos las llaves en el cajon del recibidor")
    main.repository = main.InMemoryRepository()
    data = _search(client, "llaves")
    assert len(data) == 1
    assert "llaves" in data[0]["summary"]


def test_query_vacia_es_rechazada(client: TestClient) -> None:
    response = client.get("/v1/conversation-memory/search", params={"query": " "}, headers=HEADERS)
    assert response.status_code == 422


def test_respeta_limite(client: TestClient) -> None:
    for index in range(4):
        _add(f"Recuerdo numero {index} sobre la playa")
    data = _search(client, "playa", limit=2)
    assert len(data) == 2
