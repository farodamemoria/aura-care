"""KAN-131 - la IA crea los ejercicios genericos diarios (con fallback a la rotacion fija)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402


def _clear() -> None:
    main.repository.cognitive_exercises.clear()


def test_daily_exercises_use_ai_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear()
    monkeypatch.setattr(main, "now", lambda: datetime(2026, 10, 15, 9, 0))
    monkeypatch.setattr(main, "_generate_generic_exercises_ai", lambda day, count: [
        ("recall", "¿Qué desayunaste hoy?", "Café con tostadas"),
        ("orientation", "¿Qué día de la semana es?", "Miércoles"),
        ("naming", "Nombra una fruta", "Manzana"),
    ])
    created = main.ensure_daily_generic_exercises()
    assert created == 3
    questions = {exercise.question for exercise in main.repository.cognitive_exercises.values()}
    assert "¿Qué desayunaste hoy?" in questions
    assert all(exercise.notes == "auto-daily" for exercise in main.repository.cognitive_exercises.values())


def test_daily_exercises_fall_back_to_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear()
    monkeypatch.setattr(main, "now", lambda: datetime(2026, 10, 15, 9, 0))
    monkeypatch.setattr(main, "_generate_generic_exercises_ai", lambda day, count: [])
    created = main.ensure_daily_generic_exercises()
    assert created == main.DAILY_GENERIC_COUNT
