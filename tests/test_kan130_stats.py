"""KAN-130 — Estadísticas de evolución (ejercicios cognitivos + alertas)."""

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

TOKEN = "stats-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _completed_exercise(client: TestClient, correct: bool) -> None:
    when = (main.now() - timedelta(minutes=5)).isoformat()
    exercise = client.post(
        "/v1/cognitive-exercises/scheduled", headers=HEADERS,
        json={"question": "¿Cómo me llamo?", "expected_answer": "Faro", "scheduled_at": when},
    ).json()
    client.post(f"/v1/cognitive-exercises/{exercise['id']}/answer", headers=HEADERS, json={"correct": correct})


def test_stats_evolution_daily(client: TestClient) -> None:
    _completed_exercise(client, correct=True)
    _completed_exercise(client, correct=False)
    client.post("/v1/events", headers=HEADERS, json={
        "kind": "system", "summary": "Aviso urgente", "source": "portal", "severity": "urgent",
    })

    body = client.get("/v1/stats/evolution?days=30", headers=HEADERS).json()
    assert len(body["days"]) == 30
    today = body["days"][-1]
    assert today["exercises"] == 2
    assert today["exercises_correct"] == 1
    assert today["accuracy"] == 50.0
    assert today["alerts"] == 1
    assert today["urgent"] == 1
    summary = body["summary"]
    assert summary["exercises_completed"] == 2
    assert summary["accuracy"] == 50.0
    assert summary["alerts"] == 1
    assert summary["trend"] in {"mejora", "estable", "deterioro", "sin-datos"}


def test_seed_demo_history_populates_stats(client: TestClient) -> None:
    seeded = client.post("/v1/admin/seed-demo-history?days=30", headers=HEADERS).json()
    assert seeded["status"] == "ok"
    assert seeded["exercises"] > 10
    body = client.get("/v1/stats/evolution?days=30", headers=HEADERS).json()
    assert len(body["days"]) == 30
    with_data = [day for day in body["days"] if day["exercises"]]
    assert len(with_data) >= 10  # varios días con actividad
    assert body["summary"]["exercises_completed"] >= seeded["exercises"] - 3
    assert client.post("/v1/admin/seed-demo-history").status_code == 401
