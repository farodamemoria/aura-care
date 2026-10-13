"""KAN-121 - memoria filtrada por dia y hora + busqueda + navegacion cronologica."""

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

TOKEN = "kan121-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
DAY = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _add(summary: str, when: datetime, source: str = "glasses") -> None:
    main.repository.add_event(main.EventCreate(
        kind="conversation", summary=summary, source=source, severity="info", occurred_at=when,
    ))


def test_filtro_por_dia_y_hora(client: TestClient) -> None:
    _add("Marta vino por la manana", DAY.replace(hour=10))
    _add("Paseo por la tarde", DAY.replace(hour=18))
    _add("Cena del dia anterior", DAY - timedelta(days=1))
    since = DAY.replace(hour=9).isoformat().replace("+00:00", "Z")
    until = DAY.replace(hour=13).isoformat().replace("+00:00", "Z")
    body = client.get(f"/v1/events?since={since}&until={until}", headers=HEADERS).json()
    assert [event["summary"] for event in body] == ["Marta vino por la manana"]


def test_busqueda_por_palabra_o_nombre(client: TestClient) -> None:
    _add("Marta trajo la compra", DAY)
    _add("Dormimos la siesta", DAY.replace(hour=15))
    body = client.get("/v1/events?search=Marta", headers=HEADERS).json()
    assert len(body) == 1
    assert "Marta" in body[0]["summary"]


def test_busqueda_y_dia_combinados(client: TestClient) -> None:
    _add("Marta hoy", DAY.replace(hour=9))
    _add("Marta ayer", DAY - timedelta(days=1))
    since = DAY.replace(hour=0).isoformat().replace("+00:00", "Z")
    until = DAY.replace(hour=23, minute=59).isoformat().replace("+00:00", "Z")
    body = client.get(f"/v1/events?search=Marta&since={since}&until={until}", headers=HEADERS).json()
    assert len(body) == 1
    assert body[0]["summary"] == "Marta hoy"


def test_fecha_invalida_rechazada(client: TestClient) -> None:
    response = client.get("/v1/events?since=ayer", headers=HEADERS)
    assert response.status_code == 422


def test_busqueda_demasiado_larga_rechazada(client: TestClient) -> None:
    response = client.get(f"/v1/events?search={'x' * 200}", headers=HEADERS)
    assert response.status_code == 422


def test_portal_tiene_controles_de_dia_hora_y_navegacion() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    for element in ('id="event-date"', 'id="event-hour-from"', 'id="event-hour-to"',
                    'id="event-prev-day"', 'id="event-next-day"', 'id="event-today"'):
        assert element in html, element
    assert "refreshMemoryDay" in js
    assert "shiftMemoryDay" in js
    assert "hourMatches" in js
