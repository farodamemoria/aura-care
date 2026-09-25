"""El chat familiar debe entender rangos ('esta semana' / 'este mes'), no solo un día."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402


def _today():
    return main.now().astimezone(main.family_zone()).date()


def test_week_question_returns_week_window() -> None:
    period = main.family_period("¿Hay algún registro de esta semana?", "es", _today())
    assert period is not None
    start, end, label = period
    assert label == "esta semana"
    assert timedelta(days=6) <= (end - start) <= timedelta(days=7, seconds=1)


def test_month_question_returns_month_window() -> None:
    period = main.family_period("resumen del mes", "es", _today())
    assert period is not None and period[2] == "este mes"


def test_galician_week_question() -> None:
    period = main.family_period("hai algún rexistro desta semana?", "gl", _today())
    assert period is not None and period[2] == "esta semana"


def test_plain_question_has_no_period() -> None:
    assert main.family_period("¿cómo ha ido hoy?", "es", _today()) is None


def test_week_window_includes_past_days(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    repository = main.InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    repository.add_event(main.EventCreate(
        kind="hazard", summary="Aviso de hace 3 días", source="glasses",
        occurred_at=main.now() - timedelta(days=3),
    ))
    start, end, _ = main.family_period("esta semana", "es", _today())
    events = main.family_day_events(start, end)
    assert any(event.summary == "Aviso de hace 3 días" for event in events)
