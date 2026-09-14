"""KAN-35 — Casos de uso / pruebas del motor de escucha ambiental.

Cubren los criterios de aceptación: una tos aislada no avisa, una secuencia
repetida provoca una sola pregunta, una respuesta tranquilizadora detiene el
flujo, y una petición de ayuda, persistencia o falta de respuesta escalan.
Se simulan señales acústicas (incluida ruido/falsas alarmas) de forma
determinista, sin depender del hardware.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.environmental_listening import (  # noqa: E402
    ACOUSTIC_SIGNAL_LABELS,
    CHECK_IN_QUESTION,
    EnvironmentalListeningEngine,
    ListeningConfig,
    is_help_request,
    is_reassuring,
    normalize_text,
)

BASE = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
SECOND = timedelta(seconds=1)


def make_engine(**overrides: object) -> EnvironmentalListeningEngine:
    return EnvironmentalListeningEngine(ListeningConfig(**overrides))


def burst(engine: EnvironmentalListeningEngine, signal: str, at: datetime, count: int, confidence: float = 0.9) -> list[dict]:
    return [engine.detect(signal, confidence, at + index * SECOND) for index in range(count)]


def test_isolated_cough_does_not_trigger_a_check_in() -> None:
    engine = make_engine()
    results = burst(engine, "cough", BASE, 2)
    assert all(result["action"] == "listening" for result in results)
    assert engine.active_episode is None
    assert engine.history == []


def test_repeated_cough_asks_exactly_once() -> None:
    engine = make_engine()
    results = burst(engine, "cough", BASE, 3)
    assert [result["action"] for result in results] == ["listening", "listening", "ask"]
    assert results[-1]["question"] == CHECK_IN_QUESTION
    assert engine.active_episode is not None
    assert engine.active_episode.check_ins == 1


def test_separated_detections_outside_window_do_not_accumulate() -> None:
    engine = make_engine()
    engine.detect("cough", 0.9, BASE)
    engine.detect("cough", 0.9, BASE + timedelta(seconds=10))
    result = engine.detect("cough", 0.9, BASE + timedelta(seconds=200))
    assert result["action"] == "listening"
    assert result["occurrences"] == 1


def test_low_confidence_is_ignored() -> None:
    engine = make_engine()
    results = burst(engine, "cough", BASE, 5, confidence=0.4)
    assert all(result["action"] == "ignored" and result["reason"] == "low_confidence" for result in results)


def test_unknown_signal_is_ignored() -> None:
    engine = make_engine()
    result = engine.detect("sneeze", 0.99, BASE)
    assert result["action"] == "ignored" and result["reason"] == "unknown_signal"


def test_reassuring_answer_closes_without_alerting() -> None:
    engine = make_engine()
    burst(engine, "cough", BASE, 3)
    result = engine.respond("Estoy bien, no me pasa nada", BASE + timedelta(seconds=5))
    assert result["action"] == "closed"
    assert result["outcome"] == "reassured"
    assert result["alerted"] is False
    assert engine.active_episode is None
    assert engine.history[-1].outcome == "reassured"


def test_help_request_escalates() -> None:
    engine = make_engine()
    burst(engine, "cough", BASE, 3)
    result = engine.respond("Ayuda, me duele el pecho", BASE + timedelta(seconds=5))
    assert result["action"] == "escalate"
    escalation = result["escalation"]
    assert escalation["explicit_help_request"] is True
    assert escalation["reason"] == "help_request"
    assert "tos" in escalation["spoken_message"]
    assert engine.history[-1].status == "escalated"


def test_no_response_retries_once_then_escalates() -> None:
    engine = make_engine()
    burst(engine, "cough", BASE, 3)
    retry = engine.tick(BASE + timedelta(seconds=35))
    assert retry["action"] == "ask" and retry["reason"] == "retry"
    escalated = engine.tick(BASE + timedelta(seconds=80))
    assert escalated["action"] == "escalate"
    assert escalated["escalation"]["reason"] == "no_response"
    assert escalated["escalation"]["explicit_help_request"] is False


def test_persistence_after_question_escalates() -> None:
    engine = make_engine()
    burst(engine, "cough", BASE, 3)
    result = None
    for index in range(2):
        result = engine.detect("cough", 0.9, BASE + timedelta(seconds=5 + index))
    assert result is not None and result["action"] == "escalate"
    assert result["escalation"]["reason"] == "persistence"


def test_unclear_answer_retries_then_escalates() -> None:
    engine = make_engine()
    burst(engine, "cough", BASE, 3)
    first = engine.respond("mmm no sé", BASE + timedelta(seconds=5))
    assert first["action"] == "ask" and first["reason"] == "retry"
    second = engine.respond("bueno, ya veremos", BASE + timedelta(seconds=10))
    assert second["action"] == "escalate"
    assert second["escalation"]["reason"] == "unclear_response"


def test_cooldown_suppresses_then_expires() -> None:
    engine = make_engine()
    burst(engine, "cough", BASE, 3)
    engine.respond("Ayuda", BASE + timedelta(seconds=5))
    within = burst(engine, "cough", BASE + timedelta(minutes=1), 3)
    assert all(result["action"] == "ignored" and result["reason"] == "cooldown" for result in within)
    after = burst(engine, "cough", BASE + timedelta(minutes=11), 3)
    assert after[-1]["action"] == "ask"


def test_escalation_messages_never_diagnose() -> None:
    engine = make_engine()
    burst(engine, "cough", BASE, 3)
    message = engine.respond("Ayuda", BASE + timedelta(seconds=5))["escalation"]["spoken_message"]
    normalized = normalize_text(message)
    for forbidden in ("diagnostic", "enfermedad", "neumonia", "bronquitis", "covid"):
        assert forbidden not in normalized
    assert "posible" in normalized or "paciente" in normalized


@pytest.mark.parametrize(
    "text,expected",
    [
        ("estoy bien", True),
        ("todo bien, gracias", True),
        ("nada", True),
        ("no estoy bien", False),
        ("me duele", False),
    ],
)
def test_reassurance_classifier(text: str, expected: bool) -> None:
    assert is_reassuring(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("ayuda", True),
        ("no puedo respirar", True),
        ("me duele mucho", True),
        ("estoy bien", False),
    ],
)
def test_help_classifier(text: str, expected: bool) -> None:
    assert is_help_request(text) is expected


def test_catalog_covers_a_cough_signal() -> None:
    assert "cough" in ACOUSTIC_SIGNAL_LABELS
