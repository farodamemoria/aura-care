"""Escenario 6 — ejercicios cognitivos programados, respuestas e informes."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "exercises-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _schedule(client: TestClient, minutes_ago: int = 1) -> dict:
    when = (main.now() - timedelta(minutes=minutes_ago)).isoformat()
    response = client.post(
        "/v1/cognitive-exercises/scheduled", headers=HEADERS,
        json={"question": "¿Cómo se llaman tus padres?", "expected_answer": "Ana y Luis", "scheduled_at": when},
    )
    assert response.status_code == 201
    return response.json()


def test_scheduled_exercise_is_asked_by_voice(client: TestClient) -> None:
    exercise = _schedule(client)
    assert exercise["asked_at"] is None
    assert exercise["status"] == "pending"

    tick = client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()
    assert tick["asked"] == 1

    reminders = client.get("/v1/voice-reminders", headers=HEADERS).json()
    assert reminders and reminders[0]["message"] == "¿Cómo se llaman tus padres?"

    # no se vuelve a preguntar dos veces
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 0


def test_answer_and_report(client: TestClient) -> None:
    exercise = _schedule(client)
    client.post("/v1/cognitive-exercises/tick", headers=HEADERS)

    answered = client.post(
        f"/v1/cognitive-exercises/{exercise['id']}/answer", headers=HEADERS, json={"correct": True}
    )
    assert answered.status_code == 200
    assert answered.json()["status"] == "completed"
    assert answered.json()["correct"] is True

    report = client.get("/v1/cognitive-exercises/report?period=daily", headers=HEADERS).json()
    assert report["completed"] == 1
    assert report["correct"] == 1
    assert report["accuracy"] == 100.0
    assert "diario" in report["summary"]

    summary = client.get("/v1/cognitive-exercises/summary", headers=HEADERS).json()
    assert summary["total"] == 1 and summary["completed"] == 1


def test_report_rejects_unknown_period(client: TestClient) -> None:
    assert client.get("/v1/cognitive-exercises/report?period=yearly", headers=HEADERS).status_code == 422
