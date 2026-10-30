"""KAN-129 - los registros de dias anteriores deben aparecer aunque haya muchos eventos nuevos."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan129-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _add(kind: str, summary: str, when: datetime) -> None:
    main.repository.add_event(main.EventCreate(
        kind=kind, summary=summary, source="glasses", severity="info", occurred_at=when,
    ))


def test_dia_antiguo_aparece_con_muchos_eventos_nuevos(client: TestClient) -> None:
    old_day = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    _add("routine", "Paseo por el parque", old_day)
    current = datetime.now(timezone.utc)
    for index in range(505):
        _add("conversation", f"Conversacion reciente {index}", current)

    start, end = main.family_day_window(date(2026, 9, 25))
    events = main.family_day_events(start, end)
    assert len(events) == 1
    assert events[0].summary == "Paseo por el parque"


def test_dia_sin_eventos_devuelve_vacio(client: TestClient) -> None:
    _add("routine", "Paseo", datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc))
    start, end = main.family_day_window(date(2026, 9, 23))
    assert main.family_day_events(start, end) == []


def test_pregunta_por_fecha_antigua_responde_con_datos(client: TestClient) -> None:
    _add("caregiver_action", "Jose Maria te acompano a la farmacia",
         datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc))
    now = datetime.now(timezone.utc)
    for index in range(505):
        _add("conversation", f"Conversacion {index}", now)

    response = client.post("/v1/family/ask", json={"question": "¿que paso el 25 de septiembre?"},
                           headers=HEADERS)
    assert response.status_code == 200
    assert "farmacia" in response.json()["answer"] or "1" in response.json()["answer"]
