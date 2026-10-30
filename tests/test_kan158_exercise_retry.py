"""KAN-158 - los ejercicios programados no se pierden: se entregan al reconectar y no se marcan como fallidos antes."""

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

TOKEN = "kan158-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_TICK_SCHEDULER", "0")
    main.repository = main.InMemoryRepository()
    monkeypatch.setattr(main, "ensure_daily_generic_exercises", lambda reference=None: 0)
    return TestClient(main.app)


def _schedule(client: TestClient, minutes_ago: int = 60) -> dict:
    when = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    response = client.post("/v1/cognitive-exercises/scheduled", json={
        "question": "¿Cómo se llamaba tu madre?",
        "expected_answer": "Maria",
        "scheduled_at": when,
    }, headers=HEADERS)
    assert response.status_code == 201
    return response.json()


def _exercise(exercise_id: str) -> main.CognitiveExercise:
    return main.repository.cognitive_exercises[main.UUID(exercise_id)]


def test_programado_vencido_se_encola_aunque_el_dispositivo_este_apagado(client: TestClient) -> None:
    exercise = _schedule(client, minutes_ago=240)
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 1
    assert _exercise(exercise["id"]).asked_at is None


def test_no_duplica_mientras_esta_en_cola(client: TestClient) -> None:
    _schedule(client)
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 1
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 0


def test_solo_se_marca_preguntado_cuando_se_entrega(client: TestClient) -> None:
    exercise = _schedule(client)
    client.post("/v1/cognitive-exercises/tick", headers=HEADERS)
    reminders = client.get("/v1/voice-reminders", headers=HEADERS).json()
    assert len(reminders) == 1
    assert _exercise(exercise["id"]).asked_at is not None


def test_entregado_no_se_vuelve_a_encolar(client: TestClient) -> None:
    exercise = _schedule(client)
    client.post("/v1/cognitive-exercises/tick", headers=HEADERS)
    client.get("/v1/voice-reminders", headers=HEADERS)
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 0
    assert not _exercise(exercise["id"]).abandoned


def test_futuro_no_se_encola(client: TestClient) -> None:
    _schedule(client, minutes_ago=-60)
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 0


def test_reintenta_el_que_no_se_entrego(client: TestClient) -> None:
    exercise = _schedule(client)
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 1
    client.get("/v1/voice-reminders", headers=HEADERS)
    assert _exercise(exercise["id"]).asked_at is not None

    retry = client.post(f"/v1/voice-reminders/{exercise['id']}/retry", headers=HEADERS)
    assert retry.status_code == 200
    assert _exercise(exercise["id"]).asked_at is None
    again = client.get("/v1/voice-reminders", headers=HEADERS).json()
    assert len(again) == 1
    assert _exercise(exercise["id"]).asked_at is not None
