"""KAN-35 — Escucha ambiental inteligente y escalado de posibles síntomas.

Máquina de estados pura y determinista (sin FastAPI ni base de datos) que
convierte una secuencia de detecciones acústicas de las gafas en, como mucho,
una pregunta breve de comprobación, y escala a la red de cuidados solo cuando
procede. Nunca formula diagnósticos médicos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

ACOUSTIC_SIGNAL_LABELS: dict[str, str] = {
    "cough": "tos",
    "choking": "atragantamiento",
    "fall": "golpe o caída",
    "groan": "quejido",
    "cry": "llanto",
    "shout": "grito",
}

CHECK_IN_QUESTION = "¿Estás bien?"

REASSURING_PATTERNS = (
    r"\b(estoy|toy)\s+(bien|perfecto|fenomenal|fatal no)\b",
    r"\btodo\s+bien\b",
    r"\bno\s+(me\s+)?pasa\s+nada\b",
    r"\bno\s+es\s+nada\b",
    r"^\s*(nada|na)\s*$",
)

HELP_PATTERNS = (
    r"\b(ayuda|socorro|auxilio)\b",
    r"\bno\s+(estoy|toy)\s+bien\b",
    r"\bno\s+me\s+siento\s+bien\b",
    r"\bme\s+duele\b",
    r"\bme\s+ahogo\b",
    r"\bno\s+puedo\s+(respirar|moverme|levantarme|caminar)\b",
    r"\bme\s+ca[ií]\b",
)


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def is_reassuring(text: str) -> bool:
    normalized = normalize_text(text)
    if any(re.search(pattern, normalized) for pattern in HELP_PATTERNS):
        return False
    return any(re.search(pattern, normalized) for pattern in REASSURING_PATTERNS)


def is_help_request(text: str) -> bool:
    normalized = normalize_text(text)
    return any(re.search(pattern, normalized) for pattern in HELP_PATTERNS)


LOST_PATTERNS = (
    r"\b(estoy|toy|estou)\s+(perdid[oa]|desorientad[oa])\b",
    r"\b(perdid[oa]|desorientad[oa])\s+(estoy|toy|estou)\b",
    r"\bno\s+(se|sei)\s+(donde|onde)\s+(estoy|estou)\b",
    r"\bnon\s+sei\s+(onde|donde)\s+(estou|estoy)\b",
    r"\b(me\s+)?(he\s+)?(perdid[oa]|perdin|perdinme|perdim)\b",
    r"\bnon\s+atopo\s+(o\s+)?camin?o\b",
    r"\bno\s+encuentro\s+(el\s+)?camin?o\b",
    r"\bno\s+(se|sei)\s+volver\b",
    r"\bnon\s+sei\s+volver\b",
)


def is_lost_request(text: str) -> bool:
    """Detecta peticiones de ayuda por desorientación en español y gallego."""
    normalized = normalize_text(text)
    return any(re.search(pattern, normalized) for pattern in LOST_PATTERNS)


@dataclass(frozen=True)
class ListeningConfig:
    window: timedelta = timedelta(seconds=90)
    min_occurrences: int = 3
    min_confidence: float = 0.6
    cooldown: timedelta = timedelta(minutes=10)
    response_timeout: timedelta = timedelta(seconds=30)
    max_retries: int = 1


@dataclass
class Detection:
    signal: str
    confidence: float
    at: datetime


@dataclass
class Episode:
    id: UUID
    signal: str
    started_at: datetime
    updated_at: datetime
    detections: list[Detection] = field(default_factory=list)
    status: str = "awaiting_response"
    check_ins: int = 0
    question_asked_at: Optional[datetime] = None
    response_text: Optional[str] = None
    outcome: Optional[str] = None
    escalation_reason: Optional[str] = None
    explicit_help_request: bool = False

    def snapshot(self) -> dict:
        return {
            "id": str(self.id),
            "signal": self.signal,
            "signal_label": ACOUSTIC_SIGNAL_LABELS.get(self.signal, self.signal),
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "occurrences": len(self.detections),
            "check_ins": self.check_ins,
            "question_asked_at": self.question_asked_at.isoformat() if self.question_asked_at else None,
            "response_text": self.response_text,
            "outcome": self.outcome,
            "escalation_reason": self.escalation_reason,
            "explicit_help_request": self.explicit_help_request,
        }


class EnvironmentalListeningEngine:
    """Detects relevant acoustic patterns and decides when to ask and escalate."""

    def __init__(self, config: Optional[ListeningConfig] = None) -> None:
        self.config = config or ListeningConfig()
        self.active_episode: Optional[Episode] = None
        self.history: list[Episode] = []
        self._recent: list[Detection] = []
        self._last_ended_at: Optional[datetime] = None

    def detect(self, signal: str, confidence: float, at: datetime) -> dict:
        if signal not in ACOUSTIC_SIGNAL_LABELS:
            return {"action": "ignored", "reason": "unknown_signal"}
        if confidence < self.config.min_confidence:
            return {"action": "ignored", "reason": "low_confidence"}

        active = self.active_episode
        if active is not None and active.status == "awaiting_response":
            active.detections.append(Detection(signal=signal, confidence=confidence, at=at))
            active.updated_at = at
            since_question = [
                detection for detection in active.detections
                if active.question_asked_at is not None and detection.at >= active.question_asked_at
            ]
            if len(since_question) >= self.config.min_occurrences:
                return self._escalate(active, at, reason="persistence", explicit=False)
            return {"action": "recorded", "episode_id": str(active.id)}

        if self._last_ended_at is not None and at - self._last_ended_at < self.config.cooldown:
            return {"action": "ignored", "reason": "cooldown"}

        self._recent = [item for item in self._recent if at - item.at <= self.config.window]
        self._recent.append(Detection(signal=signal, confidence=confidence, at=at))
        occurrences = sum(1 for item in self._recent if item.signal == signal)
        if occurrences >= self.config.min_occurrences:
            return self._start_episode(signal, at, confidence)
        return {"action": "listening", "occurrences": occurrences}

    def respond(self, text: str, at: datetime) -> dict:
        episode = self.active_episode
        if episode is None or episode.status != "awaiting_response":
            return {"action": "ignored", "reason": "no_active_episode"}
        episode.response_text = text
        episode.updated_at = at
        if is_help_request(text):
            return self._escalate(episode, at, reason="help_request", explicit=True)
        if is_reassuring(text):
            episode.status = "reassured"
            episode.outcome = "reassured"
            self._close(episode, at)
            return {"action": "closed", "episode_id": str(episode.id), "outcome": "reassured", "alerted": False}
        if episode.check_ins <= self.config.max_retries:
            episode.check_ins += 1
            episode.question_asked_at = at
            return {"action": "ask", "episode_id": str(episode.id), "question": CHECK_IN_QUESTION, "reason": "retry"}
        return self._escalate(episode, at, reason="unclear_response", explicit=False)

    def tick(self, at: datetime) -> dict:
        episode = self.active_episode
        if episode is None or episode.status != "awaiting_response":
            return {"action": "idle"}
        if episode.question_asked_at is None or at - episode.question_asked_at < self.config.response_timeout:
            return {"action": "awaiting_response", "episode_id": str(episode.id)}
        if episode.check_ins <= self.config.max_retries:
            episode.check_ins += 1
            episode.question_asked_at = at
            episode.updated_at = at
            return {"action": "ask", "episode_id": str(episode.id), "question": CHECK_IN_QUESTION, "reason": "retry"}
        return self._escalate(episode, at, reason="no_response", explicit=False)

    def _start_episode(self, signal: str, at: datetime, confidence: float) -> dict:
        self._recent = []
        episode = Episode(
            id=uuid4(), signal=signal, started_at=at, updated_at=at,
            detections=[Detection(signal=signal, confidence=confidence, at=at)],
            status="awaiting_response", check_ins=1, question_asked_at=at,
        )
        self.active_episode = episode
        return {"action": "ask", "episode_id": str(episode.id), "question": CHECK_IN_QUESTION, "reason": "repetition"}

    def _escalate(self, episode: Episode, at: datetime, reason: str, explicit: bool) -> dict:
        episode.status = "escalated"
        episode.outcome = "escalated"
        episode.escalation_reason = reason
        episode.explicit_help_request = explicit
        episode.updated_at = at
        label = ACOUSTIC_SIGNAL_LABELS.get(episode.signal, episode.signal)
        if reason == "help_request":
            message = f"Faro: el paciente pide ayuda después de detectar {label}."
        elif reason == "no_response":
            message = f"Faro: posible {label}; el paciente no responde a la comprobación."
        elif reason == "persistence":
            message = f"Faro: {label} persistente después de preguntar si estaba bien."
        else:
            message = f"Faro: respuesta poco clara tras detectar {label}."
        escalation = {
            "kind": "hazard",
            "spoken_message": message,
            "explicit_help_request": explicit,
            "signal": episode.signal,
            "reason": reason,
        }
        self._close(episode, at)
        return {"action": "escalate", "episode_id": str(episode.id), "outcome": "escalated", "escalation": escalation}

    def _close(self, episode: Episode, at: datetime) -> None:
        self.history.append(episode)
        self.active_episode = None
        self._recent = []
        self._last_ended_at = at
