"""KAN-131 - ejercicios genericos proactivos diarios."""

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

TOKEN = "kan131-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _auto_daily() -> list[main.CognitiveExercise]:
    return [ex for ex in main.repository.cognitive_exercises.values() if ex.notes == "auto-daily"]


def test_generacion_requiere_auth(client: TestClient) -> None:
    assert client.post("/v1/cognitive-exercises/auto-daily").status_code == 401


def test_genera_tres_ejercicios_y_es_idempotente(client: TestClient) -> None:
    first = client.post("/v1/cognitive-exercises/auto-daily", headers=HEADERS).json()
    assert first["created"] == 3
    assert len(_auto_daily()) == 3
    second = client.post("/v1/cognitive-exercises/auto-daily", headers=HEADERS).json()
    assert second["created"] == 0
    assert len(_auto_daily()) == 3
    categories = {exercise.category for exercise in _auto_daily()}
    assert categories <= {"recall", "orientation", "naming", "movement"}
    assert all(exercise.status == "pending" for exercise in _auto_daily())


def test_aparecen_en_la_lista_de_ejercicios(client: TestClient) -> None:
    client.post("/v1/cognitive-exercises/auto-daily", headers=HEADERS)
    listed = client.get("/v1/cognitive-exercises", headers=HEADERS).json()
    assert sum(1 for item in listed if item["notes"] == "auto-daily") == 3


def test_el_tick_los_crea_y_los_pregunta_por_voz(client: TestClient) -> None:
    future = (main.now() + timedelta(days=7)).replace(hour=20, minute=0, second=0, microsecond=0)
    assert main.run_exercise_tick(future) == 3
    main.repository.take_voice_reminders()
    assert all(exercise.asked_at is not None for exercise in _auto_daily())
    assert main.run_exercise_tick(future) == 0
