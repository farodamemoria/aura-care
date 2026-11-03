"""KAN-196 - el ejercicio programado no se pierde si nadie lo reproduce.

Cubre la cadena completa: tick -> cola de voz -> peek/claim -> release/ack.
Sin cliente autenticado no se consume nada; si la reproduccion falla se suelta la
reserva y el ejercicio sigue pendiente para el siguiente intento.
"""

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

TOKEN = "kan196-token-4a7d2e9c1f6b8305d1e7c2a4b9f0836d"
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


def _schedule_exercise(client: TestClient, at: datetime, question: str = "¿Qué desayunaste hoy?") -> str:
    created = client.post("/v1/cognitive-exercises/scheduled", headers=HEADERS, json={
        "question": question,
        "expected_answer": "Café",
        "scheduled_at": at.isoformat(),
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _pending(client: TestClient) -> list[dict]:
    response = client.get("/v1/voice-reminders", headers=HEADERS, params={"peek": "1"})
    assert response.status_code == 200
    return response.json()


def _asked_at(exercise_id: str):
    return main.repository.cognitive_exercises[main.UUID(exercise_id)].asked_at


def _pending_rows() -> int:
    return main.repository.event_db.execute(
        "SELECT count(*) FROM voice_reminders WHERE spoken_at IS NULL"
    ).fetchone()[0]


def test_ejercicio_programado_sin_sesion_sigue_pendiente(client: TestClient) -> None:
    exercise_id = _schedule_exercise(client, datetime.now(timezone.utc) - timedelta(minutes=1))

    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 1
    queued = _pending(client)
    assert len(queued) == 1
    assert queued[0]["kind"] == "exercise"
    assert queued[0]["event_id"] == exercise_id

    # 5 minutos de tick sin ninguna sesion autenticada: el aviso NO se consume.
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    for _ in range(5):
        assert client.post(
            "/v1/cognitive-exercises/tick", headers=HEADERS, params={"at": later.isoformat()}
        ).json()["asked"] == 0

    still = _pending(client)
    assert len(still) == 1 and still[0]["id"] == queued[0]["id"]
    assert _pending_rows() == 1
    assert _asked_at(exercise_id) is None


def test_claim_sin_ack_no_marca_el_ejercicio_y_release_lo_reintenta(client: TestClient) -> None:
    exercise_id = _schedule_exercise(client, datetime.now(timezone.utc) - timedelta(minutes=1))
    client.post("/v1/cognitive-exercises/tick", headers=HEADERS)

    claim = client.post("/v1/voice-reminders/claim", headers=HEADERS).json()
    assert len(claim["reminders"]) == 1
    reminder = claim["reminders"][0]
    assert reminder["kind"] == "exercise"
    assert _pending(client) == [], "reservado no debe ofrecerse a otro cliente"
    assert _asked_at(exercise_id) is None

    released = client.post(
        "/v1/voice-reminders/release", headers=HEADERS, json={"ids": [reminder["id"]]}
    )
    assert released.status_code == 200
    assert released.json()["released"] == 1

    pending = _pending(client)
    assert len(pending) == 1 and pending[0]["id"] == reminder["id"]
    assert _pending_rows() == 1
    assert _asked_at(exercise_id) is None


def test_ack_tras_reproducir_marca_el_ejercicio_preguntado(client: TestClient) -> None:
    exercise_id = _schedule_exercise(client, datetime.now(timezone.utc) - timedelta(minutes=1))
    client.post("/v1/cognitive-exercises/tick", headers=HEADERS)

    reminder = client.post("/v1/voice-reminders/claim", headers=HEADERS).json()["reminders"][0]
    ack = client.post("/v1/voice-reminders/ack", headers=HEADERS, json={"ids": [reminder["id"]]})
    assert ack.status_code == 200
    assert ack.json()["acked"] == 1
    assert _asked_at(exercise_id) is not None
    assert _pending(client) == []
    assert _pending_rows() == 0


def test_release_de_un_recordatorio_ya_hablado_no_hace_nada(client: TestClient) -> None:
    _schedule_exercise(client, datetime.now(timezone.utc) - timedelta(minutes=1))
    client.post("/v1/cognitive-exercises/tick", headers=HEADERS)
    reminder = client.post("/v1/voice-reminders/claim", headers=HEADERS).json()["reminders"][0]
    client.post("/v1/voice-reminders/ack", headers=HEADERS, json={"ids": [reminder["id"]]})

    released = client.post(
        "/v1/voice-reminders/release", headers=HEADERS, json={"ids": [reminder["id"]]}
    )
    assert released.json()["released"] == 0
    assert _pending(client) == []


def test_release_exige_autenticacion(client: TestClient) -> None:
    assert client.post("/v1/voice-reminders/release", json={"ids": []}).status_code == 401


def test_tick_no_duplica_el_aviso_de_un_ejercicio_ya_encolado(client: TestClient) -> None:
    _schedule_exercise(client, datetime.now(timezone.utc) - timedelta(minutes=1))
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 1
    assert client.post("/v1/cognitive-exercises/tick", headers=HEADERS).json()["asked"] == 0
    assert len(_pending(client)) == 1
