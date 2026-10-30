"""KAN-37 - panel longitudinal de crisis, riesgos y evolucion del paciente."""

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

TOKEN = "kan37-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
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


def _add(kind: str, summary: str, when: datetime, severity: str = "info") -> None:
    main.repository.add_event(main.EventCreate(
        kind=kind, summary=summary, source="glasses", severity=severity, occurred_at=when,
    ))


def test_panel_requiere_auth(client: TestClient) -> None:
    assert client.get("/v1/stats/longitudinal").status_code == 401


def test_clasifica_eventos_por_categoria(client: TestClient) -> None:
    base = main.now() - timedelta(days=1)
    _add("help_request", "Peticion de ayuda", base.replace(hour=10))
    _add("hazard", "Posible caida o golpe fuerte detectado", base.replace(hour=11))
    _add("hazard", "Aviso preventivo de cocina", base.replace(hour=12))
    _add("episode", "Se ha perdido en el mercado", base.replace(hour=13))
    _add("location", "Sesion de ubicacion iniciada", base.replace(hour=14))
    _add("caregiver_action", "Aviso enviado a la familia", base.replace(hour=15))
    body = client.get("/v1/stats/longitudinal?days=7", headers=HEADERS).json()
    totals = body["totals"]
    assert totals["help_requests"] == 1
    assert totals["impacts"] == 1
    assert totals["hazards"] == 1
    assert totals["disorientation"] == 1
    assert totals["location_incidents"] == 1
    assert totals["escalations"] == 1


def test_delta_contra_periodo_anterior(client: TestClient) -> None:
    current = main.now() - timedelta(days=1)
    previous = main.now() - timedelta(days=10)
    _add("help_request", "Ayuda actual", current)
    _add("help_request", "Ayuda anterior 1", previous)
    _add("help_request", "Ayuda anterior 2", previous)
    body = client.get("/v1/stats/longitudinal?days=7", headers=HEADERS).json()
    assert body["totals"]["help_requests"] == 1
    assert body["previous_totals"]["help_requests"] == 2
    assert body["delta_percent"]["help_requests"] == -50.0


def test_urgentes_y_distribucion_por_hora(client: TestClient) -> None:
    moment = main.now() - timedelta(days=1)
    _add("hazard", "Riesgo urgente", moment.replace(hour=9), severity="urgent")
    _add("hazard", "Riesgo leve", moment.replace(hour=9), severity="info")
    expected_hour = moment.replace(hour=9).astimezone(main.family_zone()).hour
    body = client.get("/v1/stats/longitudinal?days=7", headers=HEADERS).json()
    assert body["totals"]["urgent"] == 1
    assert body["severity"]["urgent"] == 1
    assert body["by_hour"][expected_hour] == 2
    assert sum(body["by_hour"]) == 2


def test_serie_diaria_y_vacio(client: TestClient) -> None:
    body = client.get("/v1/stats/longitudinal?days=7", headers=HEADERS).json()
    assert body["period_days"] == 7
    assert len(body["by_day"]) == 7
    assert all(point["help_requests"] == 0 for point in body["by_day"])
    assert body["delta_percent"]["help_requests"] == 0.0


def test_portal_muestra_el_panel_longitudinal() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'id="longitudinal"' in html
    assert "/v1/stats/longitudinal" in js
    assert "renderLongitudinal" in js
