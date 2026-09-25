from __future__ import annotations

import os
import json
import base64
import binascii
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated, Optional, Protocol, Union
from uuid import UUID, uuid4
import secrets
import hashlib
import hmac
import re
import unicodedata
import urllib.error
import urllib.request
import sqlite3
import math
import calendar
import threading
import logging
from cryptography.fernet import Fernet
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .environmental_listening import (
    ACOUSTIC_SIGNAL_LABELS,
    EnvironmentalListeningEngine,
    ListeningConfig,
    is_lost_request,
    normalize_text,
)

CONFIDENCE_MINIMUM = 95.0
CONFIDENCE_MEAN_MINIMUM = 95.0
FACE_DETECTION_MINIMUM = 90.0
CONSENSUS_MINIMUM = 2
SAME_PERSON_COOLDOWN = timedelta(seconds=int(os.getenv("AURA_SAME_PERSON_COOLDOWN_SECONDS", "900")))
REVIEW_COOLDOWN = timedelta(minutes=2)
EMERGENCY_ALERT_COOLDOWN = timedelta(seconds=int(os.getenv("AURA_EMERGENCY_ALERT_COOLDOWN_SECONDS", "120")))
REVIEW_IMAGE_TTL = timedelta(hours=24)
REVIEW_IMAGE_SUFFIX = ".bin"


def review_cipher() -> Fernet:
    """Cifra en reposo la evidencia visual de las revisiones (Fernet = AES + HMAC)."""
    secret = os.getenv("AURA_REVIEW_SECRET") or os.getenv("AURA_CREDENTIAL_PEPPER")
    if not secret:
        raise HTTPException(status_code=503, detail="Review encryption is not configured")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)
PATIENT_FACE_ID = UUID("00000000-0000-4000-8000-000000000001")
MEMORY_STOP_WORDS = {
    "que", "como", "cuando", "donde", "quien", "para", "por", "con", "del", "las", "los",
    "una", "uno", "unos", "unas", "esto", "esta", "ese", "esa", "sobre", "hablamos", "dije",
    "dijo", "recuerdas", "recordas", "lembras", "ayer", "hoy", "antes", "despues", "faro",
}


def normalize_memory_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    return "".join(character for character in decomposed if unicodedata.category(character) != "Mn")


def memory_terms(value: str) -> set[str]:
    return {
        term for term in re.findall(r"[a-z0-9]+", value)
        if len(term) >= 3 and term not in MEMORY_STOP_WORDS
    }


def is_transcription_artifact(value: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", normalize_memory_text(value))
    return tokens[:8] == ["faro", "da", "memoria", "nombres", "familiares", "ayuda", "perdido", "familia"]


def now() -> datetime:
    return datetime.now(timezone.utc)


class PersonCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    relationship: str = Field(min_length=1, max_length=80)
    consent_granted: bool


class PersonUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    relationship: Optional[str] = Field(default=None, min_length=1, max_length=80)
    consent_granted: Optional[bool] = None


class Person(PersonCreate):
    id: UUID
    created_at: datetime
    enrollment_samples: int = 0
    enrollment_complete: bool = False
    profile_photo_available: bool = False


class MemoryCreate(BaseModel):
    person_id: Optional[UUID] = None
    kind: str = Field(pattern="^(observation|reminder|care_note)$")
    summary: str = Field(min_length=1, max_length=500)


class Memory(MemoryCreate):
    id: UUID
    created_at: datetime


class ObjectMemoryCreate(BaseModel):
    object_name: str = Field(min_length=1, max_length=80)
    place: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    source: Optional[str] = Field(default=None, max_length=40)
    seen_at: Optional[datetime] = None


class ObjectMemory(ObjectMemoryCreate):
    id: UUID
    seen_at: datetime
    created_at: datetime


def object_memory_matches(memory: ObjectMemory, query: str) -> bool:
    """Coincidencia por nombre de objeto, sin acentos ni mayusculas."""
    query_normalized = normalize_memory_text(query).strip()
    name_normalized = normalize_memory_text(memory.object_name).strip()
    if not query_normalized or not name_normalized:
        return False
    if name_normalized in query_normalized:
        return True
    return bool(memory_terms(name_normalized) & memory_terms(query_normalized))


class MedicationPlanCreate(BaseModel):
    medication: str = Field(min_length=1, max_length=120)
    dose: Optional[str] = Field(default=None, max_length=120)
    times: list[str] = Field(min_length=1, max_length=6)
    notes: Optional[str] = Field(default=None, max_length=300)
    enabled: bool = True


class MedicationPlan(MedicationPlanCreate):
    id: UUID
    created_at: datetime


class MedicationPlanUpdate(BaseModel):
    medication: Optional[str] = Field(default=None, min_length=1, max_length=120)
    dose: Optional[str] = Field(default=None, max_length=120)
    times: Optional[list[str]] = Field(default=None, min_length=1, max_length=6)
    notes: Optional[str] = Field(default=None, max_length=300)
    enabled: Optional[bool] = None


class MedicationDose(BaseModel):
    id: UUID
    plan_id: UUID
    medication: str
    dose: Optional[str] = None
    scheduled_at: datetime
    status: str = Field(pattern="^(pending|taken|missed|escalated)$")
    confirmed_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None
    created_at: datetime


class MedicationReminder(BaseModel):
    dose_id: UUID
    medication: str
    dose: Optional[str] = None
    scheduled_at: datetime
    message: str


class MedicationEscalation(BaseModel):
    dose_id: UUID
    medication: str
    scheduled_at: datetime
    message: str
    family_alert_status: str


class MedicationTickResult(BaseModel):
    at: datetime
    reminders: list[MedicationReminder]
    escalations: list[MedicationEscalation]


class SafeZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(gt=0, le=100000)
    enabled: bool = True


class SafeZone(SafeZoneCreate):
    id: UUID
    created_at: datetime


class SafeZoneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_meters: Optional[float] = Field(default=None, gt=0, le=100000)
    enabled: Optional[bool] = None


class SafeZoneCheck(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: Optional[float] = Field(default=None, ge=0, le=10000)


class SafeZoneStatus(BaseModel):
    status: str = Field(pattern="^(inside|outside|no_zones)$")
    zone: Optional[SafeZone] = None
    distance_meters: Optional[float] = None
    message: str
    family_alert_status: Optional[str] = None


class CognitiveExerciseCreate(BaseModel):
    memory_id: UUID
    category: str = Field(default="recall", pattern="^(recall|orientation|naming)$")


class ScheduledExerciseCreate(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    expected_answer: str = Field(min_length=1, max_length=300)
    scheduled_at: datetime
    category: str = Field(default="recall", pattern="^(recall|orientation|naming)$")
    notes: Optional[str] = Field(default=None, max_length=500)


class CognitiveExercise(BaseModel):
    id: UUID
    memory_id: Optional[UUID] = None
    category: str
    question: str
    expected_answer: str
    created_at: datetime
    status: str = Field(pattern="^(pending|completed)$")
    correct: Optional[bool] = None
    answered_at: Optional[datetime] = None
    notes: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    asked_at: Optional[datetime] = None
    patient_answer: Optional[str] = None


class CognitiveExerciseAnswer(BaseModel):
    correct: bool
    notes: Optional[str] = Field(default=None, max_length=500)


class CognitiveExerciseSummary(BaseModel):
    total: int
    pending: int
    completed: int
    correct: int
    accuracy: float


class CognitiveExerciseReport(BaseModel):
    period: str
    since: datetime
    completed: int
    correct: int
    accuracy: float
    summary: str


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(default="other", pattern="^(medication|routine|appointment|other)$")
    start_at: datetime
    duration_minutes: int = Field(default=30, ge=0, le=1440)
    reminder_minutes_before: int = Field(default=15, ge=0, le=1440)
    notes: Optional[str] = Field(default=None, max_length=500)
    for_patient: bool = True
    enabled: bool = True
    recurrence: str = Field(default="none", pattern="^(none|daily|weekly|monthly)$")
    recurrence_interval: int = Field(default=1, ge=1, le=366)
    recurrence_until: Optional[date] = None
    recurrence_weekdays: Optional[list[int]] = None


class CalendarEvent(CalendarEventCreate):
    id: UUID
    created_at: datetime
    reminded_at: Optional[datetime] = None


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = Field(default=None, pattern="^(medication|routine|appointment|other)$")
    start_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    reminder_minutes_before: Optional[int] = Field(default=None, ge=0, le=1440)
    notes: Optional[str] = Field(default=None, max_length=500)
    for_patient: Optional[bool] = None
    enabled: Optional[bool] = None
    recurrence: Optional[str] = Field(default=None, pattern="^(none|daily|weekly|monthly)$")
    recurrence_interval: Optional[int] = Field(default=None, ge=1, le=366)
    recurrence_until: Optional[date] = None
    recurrence_weekdays: Optional[list[int]] = None


class CalendarReminder(BaseModel):
    event_id: UUID
    title: str
    category: str
    start_at: datetime
    message: str
    for_patient: bool = True


class VoiceReminder(BaseModel):
    event_id: UUID
    message: str
    created_at: datetime


class CalendarTickResult(BaseModel):
    at: datetime
    reminders: list[CalendarReminder]


class FaceCandidate(BaseModel):
    person_id: UUID
    confidence: float = Field(ge=0, le=100)


class RecognitionResult(BaseModel):
    status: str = Field(pattern="^(confirmed|unknown|review_required|rate_limited)$")
    person: Optional[Person] = None
    confidence: Optional[float] = None
    review_id: Optional[UUID] = None
    reason: Optional[str] = None
    is_patient: bool = False


class ReviewItem(BaseModel):
    id: UUID
    created_at: datetime
    status: str
    candidate_person_ids: list[UUID]
    confidences: list[float]
    resolved_person_id: Optional[UUID] = None


class ReviewResolution(BaseModel):
    person_id: Optional[UUID] = None


class PostalAddress(BaseModel):
    street_address: str = Field(default="", max_length=200)
    postal_code: str = Field(default="", max_length=20)
    locality: str = Field(default="", max_length=100)
    province: str = Field(default="", max_length=100)
    country: str = Field(default="España", max_length=100)
    access_notes: str = Field(default="", max_length=500)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    def label(self) -> str:
        return ", ".join(part for part in (
            self.street_address, self.postal_code, self.locality, self.province, self.country
        ) if part)


class CareContactCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    phone_e164: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    role: str = Field(default="family", pattern="^(family|caregiver)$")
    whatsapp_consent: bool
    priority: int = Field(default=1, ge=1, le=5)
    alerts_enabled: bool = True
    known_person_id: Optional[UUID] = None
    alternate_phone_e164: Optional[str] = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    address: PostalAddress = Field(default_factory=PostalAddress)
    availability_notes: str = Field(default="", max_length=500)


class CareContactUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    phone_e164: Optional[str] = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    role: Optional[str] = Field(default=None, pattern="^(family|caregiver)$")
    whatsapp_consent: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    alerts_enabled: Optional[bool] = None
    known_person_id: Optional[UUID] = None
    alternate_phone_e164: Optional[str] = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    address: Optional[PostalAddress] = None
    availability_notes: Optional[str] = Field(default=None, max_length=500)


class CareContact(CareContactCreate):
    id: UUID
    created_at: datetime


class CaredPersonProfile(BaseModel):
    preferred_name: str = Field(min_length=1, max_length=80)
    full_name: str = Field(default="", max_length=120)
    birth_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    conditions: list[str] = Field(default_factory=list, max_length=20)
    communication_preferences: str = Field(default="", max_length=1000)
    emergency_notes: str = Field(default="", max_length=1000)
    care_notes: str = Field(default="", max_length=2000)
    face_enrollment_samples: int = Field(default=0, ge=0, le=5)
    face_enrollment_complete: bool = False
    profile_photo_available: bool = False
    phone_e164: Optional[str] = Field(default=None, pattern=r"^\+[1-9]\d{7,14}$")
    home_address: PostalAddress = Field(default_factory=PostalAddress)


class LocationQuestion(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(default=100, ge=0, le=10000)
    recorded_at: Optional[datetime] = None


class LocationAnswer(BaseModel):
    status: str
    message: str
    place_label: Optional[str] = None
    distance_meters: Optional[float] = None
    accuracy_meters: float


class OnboardingCreate(BaseModel):
    cared_person: CaredPersonProfile
    family_contacts: list[CareContactCreate] = Field(min_length=1, max_length=5)
    data_processing_consent: bool


class OnboardingConfiguration(BaseModel):
    cared_person: CaredPersonProfile
    family_contacts: list[CareContact]
    data_processing_consent: bool
    configured_at: datetime


class EmergencyAlertCreate(BaseModel):
    kind: str = Field(pattern="^(episode|lost|hazard|medication|reminder)$")
    spoken_message: str = Field(min_length=1, max_length=500)
    explicit_help_request: bool
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location_accuracy_meters: Optional[float] = Field(default=None, ge=0, le=10000)
    location_source: Optional[str] = Field(default=None, pattern="^(gps|network|last_known)$")
    location_recorded_at: Optional[datetime] = None
    tracking_url: Optional[str] = Field(default=None, max_length=500)


class EmergencyAlertSubmission(EmergencyAlertCreate):
    evidence_image_base64: Optional[str] = Field(default=None, max_length=7_000_000)
    evidence_mime_type: Optional[str] = Field(default=None, pattern="^image/jpeg$")
    evidence_captured_at: Optional[datetime] = None


class EmergencyAlert(EmergencyAlertCreate):
    id: UUID
    created_at: datetime
    delivery_status: str
    provider_message_id: Optional[str] = None


LOCATION_APPROXIMATE_METERS = 50.0
LOCATION_REFRESH_AFTER = timedelta(seconds=90)
LOCATION_STALE_AFTER = timedelta(minutes=10)
LOCATION_MAX_AGE = timedelta(minutes=30)


def location_age_minutes(recorded_at: Optional[datetime], reference: Optional[datetime] = None) -> int:
    reference = reference or now()
    if recorded_at is None:
        return 0
    return max(0, int((reference - recorded_at).total_seconds() // 60))


def build_alert_message(alert: EmergencyAlertCreate, reference: Optional[datetime] = None) -> str:
    reference = reference or now()
    location = ""
    if alert.latitude is not None and alert.longitude is not None:
        location = f" https://maps.google.com/?q={alert.latitude},{alert.longitude}"
        age_minutes = location_age_minutes(alert.location_recorded_at, reference)
        stale_minutes = int(LOCATION_STALE_AFTER.total_seconds() // 60)
        if age_minutes >= stale_minutes:
            location += f" (última posición conocida, hace {age_minutes} min)"
        elif alert.location_accuracy_meters is not None:
            quality = "precisión aproximada" if alert.location_accuracy_meters > LOCATION_APPROXIMATE_METERS else "precisión"
            source = f", {alert.location_source}" if alert.location_source else ""
            location += f" ({quality}: ±{round(alert.location_accuracy_meters)} m{source})"
        elif alert.location_source:
            location += f" ({alert.location_source})"
    if alert.tracking_url:
        location += f" Seguimiento: {alert.tracking_url}"
    return f"Alerta de Faro da Memoria. Tipo: {alert.kind}. {alert.spoken_message}{location}"


def prefer_location(new: LocationPoint, current: Optional[LocationPoint]) -> bool:
    """True si la lectura nueva mejora o refresca la posición ya guardada."""
    if current is None:
        return True
    new_at = new.recorded_at or now()
    current_at = current.recorded_at or now()
    if new_at < current_at - LOCATION_REFRESH_AFTER:
        return False
    if (new.accuracy_meters is not None and current.accuracy_meters is not None
            and new.accuracy_meters > current.accuracy_meters
            and new_at - current_at < LOCATION_REFRESH_AFTER):
        return False
    return True


class EventCreate(BaseModel):
    kind: str = Field(pattern="^(conversation|episode|help_request|location|recognition|caregiver_action|hazard|object_location|routine|system)$")
    summary: str = Field(min_length=1, max_length=1000)
    source: str = Field(pattern="^(glasses|phone|portal|backend)$")
    severity: str = Field(default="info", pattern="^(info|attention|urgent)$")
    occurred_at: Optional[datetime] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    metadata: dict[str, Union[str, int, float, bool, None]] = Field(default_factory=dict)


class Event(EventCreate):
    id: UUID
    created_at: datetime


class ConversationMemoryMatch(BaseModel):
    event_id: UUID
    summary: str
    speaker: str
    occurred_at: datetime
    relevance: float = Field(ge=0)


class FamilyQuestion(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    language: Optional[str] = Field(default=None, pattern="^(es|gl|en)$")
    conversation_id: Optional[str] = Field(default=None, min_length=6, max_length=64)


class FamilyAnswerSource(BaseModel):
    event_id: UUID
    kind: str
    summary: str
    occurred_at: datetime
    speaker: Optional[str] = None


class FamilyAnswer(BaseModel):
    answer: str
    language: str
    generated_by: str = Field(pattern="^(openai|summary)$")
    window_start: datetime
    window_end: datetime
    conversation_id: str
    end_conversation: bool = False
    sources: list[FamilyAnswerSource] = Field(default_factory=list)


class LocationPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: Optional[float] = Field(default=None, ge=0, le=10000)
    source: Optional[str] = Field(default=None, pattern="^(gps|network|last_known)$")
    battery_percent: Optional[int] = Field(default=None, ge=0, le=100)
    recorded_at: Optional[datetime] = None


class LocationSessionCreate(BaseModel):
    explicit_help_request: bool = False
    automatic_hazard: bool = False
    duration_minutes: int = Field(default=60, ge=5, le=240)


class LocationSession(BaseModel):
    id: UUID
    share_token: str
    created_at: datetime
    expires_at: datetime
    status: str = Field(pattern="^(active|stopped|expired)$")
    last_location: Optional[LocationPoint] = None


class ProtectiveObservationCreate(BaseModel):
    kind: str = Field(pattern="^(cookware_heating|fridge_open|keys_location|door_open|water_running|smoke_or_fire|broken_glass|dangerous_impact)$")
    observed: bool
    confidence: float = Field(ge=0, le=1)
    description: str = Field(min_length=1, max_length=500)
    location_label: Optional[str] = Field(default=None, max_length=200)
    observed_at: Optional[datetime] = None
    evidence_image_base64: Optional[str] = Field(default=None, max_length=7_000_000)
    evidence_mime_type: Optional[str] = Field(default=None, pattern="^image/jpeg$")
    evidence_captured_at: Optional[datetime] = None


class ProtectiveObservationDecision(BaseModel):
    action: str = Field(pattern="^(none|warn|remind|remember)$")
    message: Optional[str] = None
    consecutive_observations: int
    family_alert_status: Optional[str] = None
    photo_delivery_status: Optional[str] = None
    location_included: bool = False


class AccountSummary(BaseModel):
    account_id: str
    product_name: str = "Faro de la Memoria"
    plan: str
    status: str
    billing_model: str = "flat_rate"
    interactions: str = "unlimited"
    provider_accounts_required: bool = False


class PairingInviteCreate(BaseModel):
    role: str = Field(pattern="^(family|caregiver|clinician)$")


class PairingInvite(BaseModel):
    code: str
    role: str
    expires_at: datetime


class PairingClaim(BaseModel):
    code: str = Field(min_length=8, max_length=8)


class PairingResult(BaseModel):
    care_circle_id: str
    role: str
    linked: bool
    device_credential: str


class DeviceCredentialStatus(BaseModel):
    active: bool
    care_circle_id: str
    role: str


class FaceProvider(Protocol):
    def enroll(self, person_id: UUID, images: list[bytes]) -> int: ...
    def search(self, image: bytes) -> list[FaceCandidate]: ...
    def delete(self, person_id: UUID) -> None: ...


@dataclass(frozen=True)
class AlertDelivery:
    message_id: Optional[str]
    photo_message_id: Optional[str] = None
    photo_status: str = "not_requested"
    channel: str = "text"
    template_error: Optional[str] = None


class AlertProvider(Protocol):
    def send(self, contact: CareContact, alert: EmergencyAlertCreate, image: Optional[bytes] = None) -> AlertDelivery: ...


class NoopAlertProvider:
    def send(self, contact: CareContact, alert: EmergencyAlertCreate, image: Optional[bytes] = None) -> AlertDelivery:
        return AlertDelivery(message_id=None, photo_status="test_mode" if image else "not_requested")


class MetaWhatsAppProvider:
    def __init__(
        self, phone_number_id: str, token: str, template_name: str,
        template_language: str = "es", prefer_template: bool = True,
    ) -> None:
        self.url = f"https://graph.facebook.com/v23.0/{phone_number_id}/messages"
        self.media_url = f"https://graph.facebook.com/v23.0/{phone_number_id}/media"
        self.token = token
        self.template_name = template_name
        self.template_language = template_language
        self.prefer_template = prefer_template

    def _post_json(self, payload: bytes) -> dict:
        request = urllib.request.Request(self.url, data=payload, method="POST", headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
        })
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def _upload_jpeg(self, image: bytes) -> str:
        boundary = f"faro-{secrets.token_hex(16)}"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"messaging_product\"\r\n\r\nwhatsapp\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\nimage/jpeg\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"faro-alert.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode(),
            image,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(self.media_url, data=b"".join(parts), method="POST", headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        })
        with urllib.request.urlopen(request, timeout=15) as response:
            media_id = json.loads(response.read()).get("id")
        if not media_id:
            raise RuntimeError("WhatsApp did not return a media identifier")
        return media_id

    def send(self, contact: CareContact, alert: EmergencyAlertCreate, image: Optional[bytes] = None) -> AlertDelivery:
        message = build_alert_message(alert)
        location = ""
        if alert.latitude is not None and alert.longitude is not None:
            location = f" https://maps.google.com/?q={alert.latitude},{alert.longitude}"
        text_payload = json.dumps({
            "messaging_product": "whatsapp",
            "to": contact.phone_e164.removeprefix("+"),
            "type": "text",
            "text": {"body": message},
        }).encode("utf-8")
        template_payload = json.dumps({
            "messaging_product": "whatsapp",
            "to": contact.phone_e164.removeprefix("+"),
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": self.template_language},
                "components": [{"type": "body", "parameters": [
                    {"type": "text", "text": alert.kind},
                    {"type": "text", "text": alert.spoken_message + location},
                ]}],
            },
        }).encode("utf-8")
        attempts = (
            (("template", template_payload), ("text", text_payload)) if self.prefer_template
            else (("text", text_payload), ("template", template_payload))
        )
        result, last_error, channel, template_error = None, None, "text", None
        for name, payload in attempts:
            try:
                result = self._post_json(payload)
                channel = name
                break
            except urllib.error.HTTPError as error:
                last_error = error.read().decode("utf-8", errors="replace")[:500]
                if name == "template":
                    template_error = last_error
        if result is None:
            raise RuntimeError(f"WhatsApp provider rejected text and template delivery: {last_error}")
        message_id = result.get("messages", [{}])[0].get("id")
        if not image:
            return AlertDelivery(message_id=message_id, channel=channel, template_error=template_error)
        try:
            media_id = self._upload_jpeg(image)
            photo_result = self._post_json(json.dumps({
                "messaging_product": "whatsapp",
                "to": contact.phone_e164.removeprefix("+"),
                "type": "image",
                "image": {"id": media_id, "caption": "Imagen reciente capturada por las gafas para esta alerta de Faro."},
            }).encode("utf-8"))
            photo_message_id = photo_result.get("messages", [{}])[0].get("id")
            return AlertDelivery(message_id=message_id, photo_message_id=photo_message_id, photo_status="sent", channel=channel, template_error=template_error)
        except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
            return AlertDelivery(message_id=message_id, photo_status="failed", channel=channel, template_error=template_error)


class NoopFaceProvider:
    """Safe local fallback: it never guesses a person's identity."""

    def enroll(self, person_id: UUID, images: list[bytes]) -> int:
        return len(images)

    def search(self, image: bytes) -> list[FaceCandidate]:
        return []

    def delete(self, person_id: UUID) -> None:
        return None


class NoFaceDetectedError(Exception):
    """The image was valid, but the detector could not find a face."""


class RekognitionFaceProvider:
    """Sends bytes directly to Rekognition; no face image is written to disk or S3."""

    def __init__(self, collection_id: str, region: str) -> None:
        import boto3
        self.collection_id = collection_id
        self.client = boto3.client("rekognition", region_name=region)
        try:
            self.client.create_collection(CollectionId=collection_id)
        except self.client.exceptions.ResourceAlreadyExistsException:
            pass

    def enroll(self, person_id: UUID, images: list[bytes]) -> int:
        indexed = 0
        for image in images:
            response = self.client.index_faces(
                CollectionId=self.collection_id, Image={"Bytes": image},
                ExternalImageId=str(person_id), MaxFaces=1, QualityFilter="LOW",
                DetectionAttributes=[],
            )
            indexed += len(response.get("FaceRecords", []))
        return indexed

    def search(self, image: bytes) -> list[FaceCandidate]:
        try:
            response = self.client.search_faces_by_image(
                CollectionId=self.collection_id, Image={"Bytes": image},
                FaceMatchThreshold=CONFIDENCE_MINIMUM, MaxFaces=3,
            )
        except self.client.exceptions.InvalidParameterException as exc:
            raise NoFaceDetectedError from exc
        if response.get("SearchedFaceConfidence", 0.0) < FACE_DETECTION_MINIMUM:
            raise NoFaceDetectedError
        results = []
        for match in response.get("FaceMatches", []):
            external_id = match.get("Face", {}).get("ExternalImageId")
            if external_id:
                results.append(FaceCandidate(person_id=UUID(external_id), confidence=match["Similarity"]))
        return results

    def delete(self, person_id: UUID) -> None:
        paginator = self.client.get_paginator("list_faces")
        face_ids = []
        for page in paginator.paginate(CollectionId=self.collection_id):
            face_ids.extend(face["FaceId"] for face in page.get("Faces", []) if face.get("ExternalImageId") == str(person_id))
        if face_ids:
            self.client.delete_faces(CollectionId=self.collection_id, FaceIds=face_ids)


class InMemoryRepository:
    """Development repository. DynamoDB replaces it in AWS."""

    def __init__(self) -> None:
        self.data_file = Path(os.environ["AURA_DATA_FILE"]) if os.getenv("AURA_DATA_FILE") else None
        self.people_photo_dir = (
            Path(os.environ["AURA_MEDIA_DIR"]) if os.getenv("AURA_MEDIA_DIR")
            else self.data_file.parent / "person-photos" if self.data_file else None
        )
        if self.people_photo_dir:
            self.people_photo_dir.mkdir(parents=True, exist_ok=True)
        self.review_images_dir = (
            Path(os.environ["AURA_REVIEW_MEDIA_DIR"]) if os.getenv("AURA_REVIEW_MEDIA_DIR")
            else self.data_file.parent / "review-images" if self.data_file else Path("review-images")
        )
        self.review_images_dir.mkdir(parents=True, exist_ok=True)
        self.people: dict[UUID, Person] = {}
        if self.data_file and self.data_file.exists():
            for raw in json.loads(self.data_file.read_text(encoding="utf-8")):
                person = Person.model_validate(raw)
                self.people[person.id] = person
        self.memories: dict[UUID, Memory] = {}
        self.object_memories: dict[UUID, ObjectMemory] = {}
        self.medication_plans: dict[UUID, MedicationPlan] = {}
        self.medication_doses: dict[UUID, MedicationDose] = {}
        self.safe_zones: dict[UUID, SafeZone] = {}
        self.cognitive_exercises: dict[UUID, CognitiveExercise] = {}
        self.calendar_events: dict[UUID, CalendarEvent] = {}
        self.reviews: dict[UUID, ReviewItem] = {}
        self.recognition_times: dict[str, deque[datetime]] = defaultdict(deque)
        self.last_outcome: dict[str, datetime] = {}
        self.last_review_created: dict[str, datetime] = {}
        self.last_glasses_not_worn: dict[str, datetime] = {}
        self.care_contacts: dict[UUID, CareContact] = {}
        self.emergency_alerts: dict[UUID, EmergencyAlert] = {}
        self.last_emergency_at: dict[str, datetime] = {}
        self.location_sessions: dict[UUID, LocationSession] = {}
        self.protective_observations: dict[str, deque[ProtectiveObservationCreate]] = defaultdict(deque)
        self.last_protective_action: dict[str, datetime] = {}
        self.last_auto_alert: dict[str, datetime] = {}
        event_db_path = os.getenv("AURA_EVENT_DB")
        self.event_db = sqlite3.connect(event_db_path or ":memory:", check_same_thread=False)
        self.event_db.row_factory = sqlite3.Row
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, occurred_at TEXT NOT NULL,
            kind TEXT NOT NULL, summary TEXT NOT NULL, source TEXT NOT NULL, severity TEXT NOT NULL,
            latitude REAL, longitude REAL, metadata_json TEXT NOT NULL
        )""")
        self.event_db.execute("CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events(occurred_at DESC)")
        self.event_db.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, occurred_at DESC)")
        self.event_db.execute("CREATE TABLE IF NOT EXISTS configuration (key TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS pairing_invites (
            code_hash TEXT PRIMARY KEY, role TEXT NOT NULL, care_circle_id TEXT NOT NULL,
            expires_at TEXT NOT NULL, consumed_at TEXT
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS device_credentials (
            id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, care_circle_id TEXT NOT NULL,
            role TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT
        )""")
        self.event_db.execute("CREATE INDEX IF NOT EXISTS idx_device_credentials_token ON device_credentials(token_hash)")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, person_id TEXT, kind TEXT NOT NULL,
            summary TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS object_memories (
            id TEXT PRIMARY KEY, object_name TEXT NOT NULL, place TEXT,
            description TEXT, confidence REAL, source TEXT,
            seen_at TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS medication_plans (
            id TEXT PRIMARY KEY, medication TEXT NOT NULL, dose TEXT, times_json TEXT NOT NULL,
            notes TEXT, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS medication_doses (
            id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, medication TEXT NOT NULL, dose TEXT,
            scheduled_at TEXT NOT NULL, status TEXT NOT NULL, confirmed_at TEXT,
            escalated_at TEXT, created_at TEXT NOT NULL
        )""")
        self.event_db.execute("CREATE INDEX IF NOT EXISTS idx_medication_doses ON medication_doses(plan_id, scheduled_at)")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS safe_zones (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
            radius_meters REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS cognitive_exercises (
            id TEXT PRIMARY KEY, memory_id TEXT, category TEXT NOT NULL, question TEXT NOT NULL,
            expected_answer TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
            correct INTEGER, answered_at TEXT, notes TEXT,
            scheduled_at TEXT, asked_at TEXT, patient_answer TEXT
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS calendar_events (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, start_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL, reminder_minutes_before INTEGER NOT NULL,
            notes TEXT, for_patient INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, reminded_at TEXT,
            recurrence TEXT NOT NULL DEFAULT 'none', recurrence_interval INTEGER NOT NULL DEFAULT 1,
            recurrence_until TEXT, recurrence_weekdays TEXT
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
            candidate_person_ids TEXT NOT NULL, confidences TEXT NOT NULL, resolved_person_id TEXT
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS family_messages (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL
        )""")
        self.event_db.execute("CREATE INDEX IF NOT EXISTS idx_family_messages ON family_messages(conversation_id, created_at)")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS whatsapp_status (
            wamid TEXT PRIMARY KEY, status TEXT NOT NULL, recipient TEXT,
            errors TEXT, updated_at TEXT NOT NULL
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS family_alert_rules (
            id TEXT PRIMARY KEY, keywords TEXT NOT NULL, description TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )""")
        self.event_db.execute("""CREATE TABLE IF NOT EXISTS voice_reminders (
            id TEXT PRIMARY KEY, event_id TEXT NOT NULL, message TEXT NOT NULL,
            created_at TEXT NOT NULL, spoken_at TEXT
        )""")
        calendar_columns = {row[1] for row in self.event_db.execute("PRAGMA table_info(calendar_events)").fetchall()}
        for column, statement in (
            ("recurrence", "ALTER TABLE calendar_events ADD COLUMN recurrence TEXT NOT NULL DEFAULT 'none'"),
            ("recurrence_interval", "ALTER TABLE calendar_events ADD COLUMN recurrence_interval INTEGER NOT NULL DEFAULT 1"),
            ("recurrence_until", "ALTER TABLE calendar_events ADD COLUMN recurrence_until TEXT"),
            ("recurrence_weekdays", "ALTER TABLE calendar_events ADD COLUMN recurrence_weekdays TEXT"),
        ):
            if column not in calendar_columns:
                self.event_db.execute(statement)
        exercise_columns = {row[1] for row in self.event_db.execute("PRAGMA table_info(cognitive_exercises)").fetchall()}
        for column, statement in (
            ("scheduled_at", "ALTER TABLE cognitive_exercises ADD COLUMN scheduled_at TEXT"),
            ("asked_at", "ALTER TABLE cognitive_exercises ADD COLUMN asked_at TEXT"),
            ("patient_answer", "ALTER TABLE cognitive_exercises ADD COLUMN patient_answer TEXT"),
        ):
            if column not in exercise_columns:
                self.event_db.execute(statement)
        self.event_db.commit()
        for row in self.event_db.execute("SELECT * FROM memories ORDER BY created_at ASC").fetchall():
            memory = Memory(
                id=row["id"], person_id=row["person_id"], kind=row["kind"],
                summary=row["summary"], created_at=row["created_at"],
            )
            self.memories[memory.id] = memory
        for row in self.event_db.execute("SELECT * FROM object_memories ORDER BY seen_at ASC").fetchall():
            object_memory = ObjectMemory(
                id=row["id"], object_name=row["object_name"], place=row["place"],
                description=row["description"], confidence=row["confidence"], source=row["source"],
                seen_at=row["seen_at"], created_at=row["created_at"],
            )
            self.object_memories[object_memory.id] = object_memory
        for row in self.event_db.execute("SELECT * FROM medication_plans ORDER BY created_at ASC").fetchall():
            plan = MedicationPlan(
                id=row["id"], medication=row["medication"], dose=row["dose"],
                times=json.loads(row["times_json"]), notes=row["notes"],
                enabled=bool(row["enabled"]), created_at=row["created_at"],
            )
            self.medication_plans[plan.id] = plan
        for row in self.event_db.execute("SELECT * FROM medication_doses ORDER BY scheduled_at ASC").fetchall():
            dose = MedicationDose(
                id=row["id"], plan_id=row["plan_id"], medication=row["medication"], dose=row["dose"],
                scheduled_at=row["scheduled_at"], status=row["status"], confirmed_at=row["confirmed_at"],
                escalated_at=row["escalated_at"], created_at=row["created_at"],
            )
            self.medication_doses[dose.id] = dose
        for row in self.event_db.execute("SELECT * FROM safe_zones ORDER BY created_at ASC").fetchall():
            zone = SafeZone(
                id=row["id"], name=row["name"], latitude=row["latitude"], longitude=row["longitude"],
                radius_meters=row["radius_meters"], enabled=bool(row["enabled"]), created_at=row["created_at"],
            )
            self.safe_zones[zone.id] = zone
        for row in self.event_db.execute("SELECT * FROM cognitive_exercises ORDER BY created_at ASC").fetchall():
            keys = row.keys()
            raw_memory = row["memory_id"]
            exercise = CognitiveExercise(
                id=row["id"],
                memory_id=None if raw_memory in (None, "", "None") else UUID(raw_memory),
                category=row["category"],
                question=row["question"], expected_answer=row["expected_answer"],
                created_at=row["created_at"], status=row["status"],
                correct=(None if row["correct"] is None else bool(row["correct"])),
                answered_at=row["answered_at"], notes=row["notes"],
                scheduled_at=row["scheduled_at"] if "scheduled_at" in keys else None,
                asked_at=row["asked_at"] if "asked_at" in keys else None,
                patient_answer=row["patient_answer"] if "patient_answer" in keys else None,
            )
            self.cognitive_exercises[exercise.id] = exercise
        for row in self.event_db.execute("SELECT * FROM calendar_events ORDER BY start_at ASC").fetchall():
            calendar_event = CalendarEvent(
                id=row["id"], title=row["title"], category=row["category"], start_at=row["start_at"],
                duration_minutes=row["duration_minutes"],
                reminder_minutes_before=row["reminder_minutes_before"], notes=row["notes"],
                for_patient=bool(row["for_patient"]), enabled=bool(row["enabled"]),
                created_at=row["created_at"], reminded_at=row["reminded_at"],
                recurrence=row["recurrence"] or "none",
                recurrence_interval=row["recurrence_interval"] or 1,
                recurrence_until=row["recurrence_until"],
                recurrence_weekdays=(
                    json.loads(row["recurrence_weekdays"]) if row["recurrence_weekdays"] else None
                ),
            )
            self.calendar_events[calendar_event.id] = calendar_event
        for row in self.event_db.execute("SELECT * FROM reviews ORDER BY created_at ASC").fetchall():
            review = ReviewItem(
                id=UUID(row["id"]), created_at=datetime.fromisoformat(row["created_at"]),
                status=row["status"],
                candidate_person_ids=[UUID(value) for value in json.loads(row["candidate_person_ids"])],
                confidences=list(json.loads(row["confidences"])),
                resolved_person_id=(UUID(row["resolved_person_id"]) if row["resolved_person_id"] else None),
            )
            self.reviews[review.id] = review
        contacts_row = self.event_db.execute("SELECT value_json FROM configuration WHERE key='care_contacts'").fetchone()
        if contacts_row:
            for raw in json.loads(contacts_row[0]):
                contact = CareContact.model_validate(raw)
                self.care_contacts[contact.id] = contact
        locations_row = self.event_db.execute("SELECT value_json FROM configuration WHERE key='location_sessions'").fetchone()
        if locations_row:
            for raw in json.loads(locations_row[0]):
                session = LocationSession.model_validate(raw)
                self.location_sessions[session.id] = session
        self.lock = Lock()
        self.purge_expired_reviews()

    def _review_evidence_path(self, review_id: UUID) -> Path:
        return self.review_images_dir / f"{review_id}{REVIEW_IMAGE_SUFFIX}"

    def save_review(self, review: ReviewItem) -> None:
        self.reviews[review.id] = review
        with self.lock:
            self.event_db.execute(
                "INSERT INTO reviews(id, created_at, status, candidate_person_ids, confidences, resolved_person_id) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                "candidate_person_ids=excluded.candidate_person_ids, confidences=excluded.confidences, "
                "resolved_person_id=excluded.resolved_person_id",
                (
                    str(review.id), review.created_at.isoformat(), review.status,
                    json.dumps([str(person_id) for person_id in review.candidate_person_ids]),
                    json.dumps(review.confidences),
                    (str(review.resolved_person_id) if review.resolved_person_id else None),
                ),
            )
            self.event_db.commit()

    def save_review_image(self, review_id: UUID, image: bytes) -> None:
        path = self._review_evidence_path(review_id)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(review_cipher().encrypt(image))
        os.replace(temporary, path)

    def load_review_image(self, review_id: UUID) -> Optional[bytes]:
        path = self._review_evidence_path(review_id)
        if not path.exists():
            return None
        try:
            return review_cipher().decrypt(path.read_bytes())
        except Exception:  # noqa: BLE001 - una evidencia ilegible se trata como ausente
            return None

    def delete_review_evidence(self, review_id: UUID) -> None:
        path = self._review_evidence_path(review_id)
        if not path.exists():
            return
        try:
            size = path.stat().st_size
            with path.open("r+b") as handle:
                handle.write(b"\x00" * size)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass
        path.unlink(missing_ok=True)

    def purge_expired_reviews(self) -> None:
        expired = [
            review for review in self.reviews.values()
            if review.status == "pending" and review.created_at < now() - REVIEW_IMAGE_TTL
        ]
        for review in expired:
            self.delete_review_evidence(review.id)
            self.save_review(review.model_copy(update={"status": "expired"}))

    def save_people(self) -> None:
        if self.data_file is None:
            return
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.data_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps([person.model_dump(mode="json") for person in self.people.values()], ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.data_file)

    def add_event(self, request: EventCreate) -> Event:
        event = Event(
            id=uuid4(), created_at=now(),
            occurred_at=request.occurred_at or now(),
            **request.model_dump(exclude={"occurred_at"}),
        )
        with self.lock:
            self.event_db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(event.id), event.created_at.isoformat(), event.occurred_at.isoformat(), event.kind,
                 event.summary, event.source, event.severity, event.latitude, event.longitude,
                 json.dumps(event.metadata, ensure_ascii=False)),
            )
            self.event_db.commit()
        return event

    def list_events(self, limit: int, kind: Optional[str]) -> list[Event]:
        query = "SELECT * FROM events"
        params: list[object] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(limit)
        return [Event(
            id=row["id"], created_at=row["created_at"], occurred_at=row["occurred_at"],
            kind=row["kind"], summary=row["summary"], source=row["source"], severity=row["severity"],
            latitude=row["latitude"], longitude=row["longitude"], metadata=json.loads(row["metadata_json"]),
        ) for row in self.event_db.execute(query, params).fetchall()]

    def clear_events(self) -> int:
        with self.lock:
            cursor = self.event_db.execute("DELETE FROM events")
            self.event_db.commit()
            return cursor.rowcount

    def search_conversations(self, query: str, limit: int) -> list[ConversationMemoryMatch]:
        query_normalized = normalize_memory_text(query)
        query_terms = memory_terms(query_normalized)
        candidates = self.list_events(500, "conversation")
        ranked: list[tuple[float, Event]] = []
        seen: set[tuple[str, str]] = set()
        for event in candidates:
            summary_normalized = normalize_memory_text(event.summary)
            if is_transcription_artifact(event.summary):
                continue
            speaker = str(event.metadata.get("speaker", "unknown"))
            dedup_key = (speaker, summary_normalized)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            summary_terms = memory_terms(summary_normalized)
            shared = query_terms & summary_terms
            if not shared:
                continue
            exact_bonus = 2.0 if query_normalized in summary_normalized else 0.0
            coverage = len(shared) / max(len(query_terms), 1)
            frequency = sum(summary_normalized.count(term) for term in shared)
            age_days = max((now() - event.occurred_at).total_seconds(), 0) / 86400
            recency_bonus = 0.25 / (1 + age_days)
            ranked.append((round(coverage * 4 + frequency + exact_bonus + recency_bonus, 4), event))
        ranked.sort(key=lambda item: (item[0], item[1].occurred_at), reverse=True)
        return [ConversationMemoryMatch(
            event_id=event.id,
            summary=event.summary,
            speaker=str(event.metadata.get("speaker", "unknown")),
            occurred_at=event.occurred_at,
            relevance=score,
        ) for score, event in ranked[:limit]]

    def add_family_message(self, conversation_id: str, role: str, content: str) -> None:
        with self.lock:
            self.event_db.execute(
                "INSERT INTO family_messages VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), conversation_id, role, content[:2000], now().isoformat()),
            )
            self.event_db.commit()

    def family_messages(self, conversation_id: str, limit: int = 12) -> list[dict[str, str]]:
        rows = self.event_db.execute(
            "SELECT role, content FROM family_messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def update_event_metadata(self, event_id: UUID, extra: dict) -> None:
        with self.lock:
            row = self.event_db.execute(
                "SELECT metadata_json FROM events WHERE id=?", (str(event_id),)
            ).fetchone()
            if row is None:
                return
            metadata = json.loads(row["metadata_json"])
            metadata.update(extra)
            self.event_db.execute(
                "UPDATE events SET metadata_json=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), str(event_id)),
            )
            self.event_db.commit()

    def record_whatsapp_status(self, wamid: str, status: str, recipient: str, errors: str) -> None:
        with self.lock:
            self.event_db.execute(
                "INSERT OR REPLACE INTO whatsapp_status VALUES (?, ?, ?, ?, ?)",
                (wamid, status, recipient, errors, now().isoformat()),
            )
            self.event_db.commit()

    def add_family_alert_rule(self, keywords: list[str], description: str) -> dict:
        rule = {
            "id": str(uuid4()),
            "keywords": ",".join(keyword.strip() for keyword in keywords if keyword.strip())[:500],
            "description": description.strip()[:300],
            "created_at": now().isoformat(),
        }
        with self.lock:
            self.event_db.execute(
                "INSERT INTO family_alert_rules VALUES (?, ?, ?, 1, ?)",
                (rule["id"], rule["keywords"], rule["description"], rule["created_at"]),
            )
            self.event_db.commit()
        return rule

    def enqueue_voice_reminder(self, event_id: UUID, message: str) -> None:
        with self.lock:
            self.event_db.execute(
                "INSERT INTO voice_reminders(id, event_id, message, created_at, spoken_at) "
                "VALUES (?, ?, ?, ?, NULL)",
                (str(uuid4()), str(event_id), message, now().isoformat()),
            )
            self.event_db.commit()

    def take_voice_reminders(self) -> list[dict]:
        with self.lock:
            rows = self.event_db.execute(
                "SELECT id, event_id, message, created_at FROM voice_reminders "
                "WHERE spoken_at IS NULL ORDER BY created_at ASC LIMIT 20"
            ).fetchall()
            if rows:
                stamp = now().isoformat()
                self.event_db.executemany(
                    "UPDATE voice_reminders SET spoken_at=? WHERE id=?",
                    [(stamp, row["id"]) for row in rows],
                )
                self.event_db.commit()
            return [dict(row) for row in rows]

    def list_family_alert_rules(self) -> list[dict]:
        rows = self.event_db.execute(
            "SELECT id, keywords, description, enabled, created_at FROM family_alert_rules "
            "WHERE enabled=1 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def save_onboarding(self, configuration: OnboardingConfiguration) -> None:
        with self.lock:
            self.event_db.execute(
                "INSERT OR REPLACE INTO configuration(key, value_json) VALUES('onboarding', ?)",
                (configuration.model_dump_json(),),
            )
            self.event_db.commit()

    def save_patient_profile(self, profile: CaredPersonProfile) -> None:
        with self.lock:
            self.event_db.execute(
                "INSERT OR REPLACE INTO configuration(key, value_json) VALUES('patient_profile', ?)",
                (profile.model_dump_json(),),
            )
            self.event_db.commit()

    def save_care_contacts(self) -> None:
        with self.lock:
            payload = json.dumps(
                [contact.model_dump(mode="json") for contact in self.care_contacts.values()],
                ensure_ascii=False,
            )
            self.event_db.execute(
                "INSERT OR REPLACE INTO configuration(key, value_json) VALUES('care_contacts', ?)",
                (payload,),
            )
            self.event_db.commit()

    def save_location_sessions(self) -> None:
        with self.lock:
            payload = json.dumps(
                [session.model_dump(mode="json") for session in self.location_sessions.values()],
                ensure_ascii=False,
            )
            self.event_db.execute(
                "INSERT OR REPLACE INTO configuration(key, value_json) VALUES('location_sessions', ?)",
                (payload,),
            )
            self.event_db.commit()

    def save_memories(self) -> None:
        with self.lock:
            self.event_db.execute("DELETE FROM memories")
            self.event_db.executemany(
                "INSERT INTO memories(id, person_id, kind, summary, created_at) VALUES (?, ?, ?, ?, ?)",
                [
                    (str(memory.id), str(memory.person_id) if memory.person_id else None,
                     memory.kind, memory.summary, memory.created_at.isoformat())
                    for memory in self.memories.values()
                ],
            )
            self.event_db.commit()

    def save_object_memories(self) -> None:
        with self.lock:
            self.event_db.execute("DELETE FROM object_memories")
            self.event_db.executemany(
                "INSERT INTO object_memories(id, object_name, place, description, confidence, source, seen_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(memory.id), memory.object_name, memory.place, memory.description,
                     memory.confidence, memory.source, memory.seen_at.isoformat(),
                     memory.created_at.isoformat())
                    for memory in self.object_memories.values()
                ],
            )
            self.event_db.commit()

    def save_medication_plans(self) -> None:
        with self.lock:
            self.event_db.execute("DELETE FROM medication_plans")
            self.event_db.executemany(
                "INSERT INTO medication_plans(id, medication, dose, times_json, notes, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(plan.id), plan.medication, plan.dose, json.dumps(plan.times),
                     plan.notes, 1 if plan.enabled else 0, plan.created_at.isoformat())
                    for plan in self.medication_plans.values()
                ],
            )
            self.event_db.commit()

    def save_medication_doses(self) -> None:
        with self.lock:
            self.event_db.execute("DELETE FROM medication_doses")
            self.event_db.executemany(
                "INSERT INTO medication_doses(id, plan_id, medication, dose, scheduled_at, status, confirmed_at, escalated_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(dose.id), str(dose.plan_id), dose.medication, dose.dose,
                     dose.scheduled_at.isoformat(), dose.status,
                     dose.confirmed_at.isoformat() if dose.confirmed_at else None,
                     dose.escalated_at.isoformat() if dose.escalated_at else None,
                     dose.created_at.isoformat())
                    for dose in self.medication_doses.values()
                ],
            )
            self.event_db.commit()

    def save_safe_zones(self) -> None:
        with self.lock:
            self.event_db.execute("DELETE FROM safe_zones")
            self.event_db.executemany(
                "INSERT INTO safe_zones(id, name, latitude, longitude, radius_meters, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(zone.id), zone.name, zone.latitude, zone.longitude, zone.radius_meters,
                     1 if zone.enabled else 0, zone.created_at.isoformat())
                     for zone in self.safe_zones.values()
                ],
            )
            self.event_db.commit()

    def save_cognitive_exercises(self) -> None:
        with self.lock:
            self.event_db.execute("DELETE FROM cognitive_exercises")
            self.event_db.executemany(
                "INSERT INTO cognitive_exercises(id, memory_id, category, question, expected_answer, "
                "created_at, status, correct, answered_at, notes, scheduled_at, asked_at, patient_answer) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(exercise.id), "" if exercise.memory_id is None else str(exercise.memory_id),
                     exercise.category, exercise.question,
                     exercise.expected_answer, exercise.created_at.isoformat(), exercise.status,
                     None if exercise.correct is None else (1 if exercise.correct else 0),
                     exercise.answered_at.isoformat() if exercise.answered_at else None,
                     exercise.notes,
                     exercise.scheduled_at.isoformat() if exercise.scheduled_at else None,
                     exercise.asked_at.isoformat() if exercise.asked_at else None,
                     exercise.patient_answer)
                    for exercise in self.cognitive_exercises.values()
                ],
            )
            self.event_db.commit()

    def save_calendar_events(self) -> None:
        with self.lock:
            self.event_db.execute("DELETE FROM calendar_events")
            self.event_db.executemany(
                "INSERT INTO calendar_events(id, title, category, start_at, duration_minutes, "
                "reminder_minutes_before, notes, for_patient, enabled, created_at, reminded_at, "
                "recurrence, recurrence_interval, recurrence_until, recurrence_weekdays) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (str(event.id), event.title, event.category, event.start_at.isoformat(),
                     event.duration_minutes, event.reminder_minutes_before, event.notes,
                     1 if event.for_patient else 0, 1 if event.enabled else 0,
                     event.created_at.isoformat(),
                     event.reminded_at.isoformat() if event.reminded_at else None,
                     event.recurrence, event.recurrence_interval,
                     event.recurrence_until.isoformat() if event.recurrence_until else None,
                     json.dumps(event.recurrence_weekdays) if event.recurrence_weekdays is not None else None)
                    for event in self.calendar_events.values()
                ],
            )
            self.event_db.commit()

    def save_person_photo(self, person_id: UUID, image: bytes) -> bool:
        return self.save_person_photos(person_id, [image]) == 1

    def save_person_photos(self, person_id: UUID, images: list[bytes]) -> int:
        if self.people_photo_dir is None:
            return 0
        self.delete_person_photo(person_id)
        for index, image in enumerate(images[:5], start=1):
            extension = ".png" if image.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
            (self.people_photo_dir / f"{person_id}-{index}{extension}").write_bytes(image)
        return min(len(images), 5)

    def person_photo(self, person_id: UUID) -> Optional[tuple[bytes, str]]:
        photo = self.person_photo_sample(person_id, 1)
        if photo is not None:
            return photo
        if self.people_photo_dir is None:
            return None
        for extension, media_type in ((".jpg", "image/jpeg"), (".png", "image/png")):
            path = self.people_photo_dir / f"{person_id}{extension}"
            if path.is_file():
                return path.read_bytes(), media_type
        return None

    def person_photo_sample(self, person_id: UUID, sample_index: int) -> Optional[tuple[bytes, str]]:
        if self.people_photo_dir is None or sample_index not in range(1, 6):
            return None
        for extension, media_type in ((".jpg", "image/jpeg"), (".png", "image/png")):
            path = self.people_photo_dir / f"{person_id}-{sample_index}{extension}"
            if path.is_file():
                return path.read_bytes(), media_type
        return None

    def delete_person_photo(self, person_id: UUID) -> None:
        if self.people_photo_dir is None:
            return
        for extension in (".jpg", ".png"):
            for stem in (str(person_id), *(f"{person_id}-{index}" for index in range(1, 6))):
                path = self.people_photo_dir / f"{stem}{extension}"
                if path.is_file():
                    path.unlink()

    def get_onboarding(self) -> Optional[OnboardingConfiguration]:
        row = self.event_db.execute("SELECT value_json FROM configuration WHERE key='onboarding'").fetchone()
        return OnboardingConfiguration.model_validate_json(row[0]) if row else None

    def get_patient_profile(self) -> Optional[CaredPersonProfile]:
        row = self.event_db.execute("SELECT value_json FROM configuration WHERE key='patient_profile'").fetchone()
        if row:
            return CaredPersonProfile.model_validate_json(row[0])
        onboarding = self.get_onboarding()
        return onboarding.cared_person if onboarding else None


def build_face_provider() -> FaceProvider:
    if os.getenv("AURA_FACE_PROVIDER", "noop").lower() != "rekognition":
        return NoopFaceProvider()
    return RekognitionFaceProvider(
        os.environ["AURA_REKOGNITION_COLLECTION"], os.getenv("AWS_REGION", "eu-west-1")
    )


def build_alert_provider() -> AlertProvider:
    phone_number_id = os.getenv("AURA_WHATSAPP_PHONE_NUMBER_ID")
    token = os.getenv("AURA_WHATSAPP_TOKEN")
    if not phone_number_id or not token:
        return NoopAlertProvider()
    prefer_template = os.getenv("AURA_WHATSAPP_PREFER_TEMPLATE", "1").lower() not in {"0", "false", "no"}
    return MetaWhatsAppProvider(
        phone_number_id, token,
        os.getenv("AURA_WHATSAPP_TEMPLATE", "faro_emergency_alert"),
        os.getenv("AURA_WHATSAPP_TEMPLATE_LANG", "es"),
        prefer_template,
    )


repository = InMemoryRepository()
face_provider: FaceProvider = build_face_provider()
alert_provider: AlertProvider = build_alert_provider()
app = FastAPI(title="AURA Care", version="0.2.0")
web_dir = Path(__file__).resolve().parent.parent / "web"
app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

API_VERSION = "2026-08-26-patient-self-recognition-v1"


def require_auth(authorization: Optional[str]) -> str:
    configured_token = os.getenv("AURA_LOCAL_TOKEN")
    if not configured_token:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    scheme, separator, credential = (authorization or "").partition(" ")
    if (
        separator != " "
        or scheme.casefold() != "bearer"
        or not credential
        or not hmac.compare_digest(credential, configured_token)
    ):
        raise HTTPException(status_code=401, detail="Authentication required")
    return "local-care-circle"


def credential_hash(secret: str) -> str:
    """Hash bearer material with a server-side pepper; plaintext is never persisted."""
    pepper = os.getenv("AURA_CREDENTIAL_PEPPER") or os.getenv("AURA_LOCAL_TOKEN")
    if not pepper:
        raise HTTPException(status_code=503, detail="Credential hashing is not configured")
    return hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def extract_bearer(authorization: Optional[str]) -> str:
    scheme, separator, credential = (authorization or "").partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not credential:
        raise HTTPException(status_code=401, detail="Device authentication required")
    return credential


def enabled_alert_contacts() -> list[CareContact]:
    return [
        contact for contact in sorted(repository.care_contacts.values(), key=lambda value: value.priority)
        if contact.whatsapp_consent and contact.alerts_enabled
    ]


def send_alert_to_contacts(
    contacts: list[CareContact], alert: EmergencyAlertCreate, image: Optional[bytes] = None,
) -> tuple[list[tuple[CareContact, AlertDelivery]], list[str]]:
    deliveries: list[tuple[CareContact, AlertDelivery]] = []
    failures: list[str] = []
    for contact in contacts:
        try:
            deliveries.append((contact, alert_provider.send(contact, alert, image=image)))
        except RuntimeError as error:
            failures.append(f"{contact.display_name}:{error}")
        except Exception as error:  # noqa: BLE001 - un fallo de un contacto no debe tumbar el tick
            failures.append(f"{contact.display_name}:{type(error).__name__}:{error}")
    return deliveries, failures


FAMILY_ALERT_PATTERNS: dict[str, str] = {
    "pain": r"\b(dolor\w*|duele\w*|doler\w*|molest\w*|malestar\w*|dor|doe|doen|doer\w*)\b",
    "fall": r"\b(caid\w*|caer\w*|caeu|caiu|cain|cai|golpe\w*|mareo\w*|mare\w*|desma\w*|tropiez\w*|trope\w*|tropez\w*|atragant\w*)\b",
    "breathing": r"\b(respir\w*|asfix\w*|ahog\w*|ahogo|fatiga\w*)\b",
}
FAMILY_ALERT_LABELS: dict[str, str] = {
    "pain": "posible dolor",
    "fall": "posible caída o golpe",
    "breathing": "dificultad para respirar",
}
FAMILY_ALERT_KIND: dict[str, str] = {"pain": "episode", "fall": "hazard", "breathing": "hazard"}
FAMILY_ALERT_DEDUP = timedelta(minutes=15)


def detect_family_alert_category(text: str) -> Optional[str]:
    """Classify a patient utterance against the family alert criteria."""
    normalized = normalize_memory_text(text)
    for category, pattern in FAMILY_ALERT_PATTERNS.items():
        if re.search(pattern, normalized):
            return category
    return None


def detect_custom_alert_rule(text: str) -> Optional[dict]:
    """Match a patient utterance against the family-configured alert rules."""
    normalized = normalize_memory_text(text)
    for rule in repository.list_family_alert_rules():
        for keyword in rule["keywords"].split(","):
            keyword = normalize_memory_text(keyword.strip())
            if keyword and re.search(rf"\b{re.escape(keyword)}\w*", normalized):
                return rule
    return None


def maybe_send_family_alert(event: Event) -> Optional[dict]:
    """Send a WhatsApp alert to the care network when a patient utterance matches the criteria."""
    if event.kind != "conversation" or str(event.metadata.get("speaker", "")) == "faro":
        return None
    category = detect_family_alert_category(event.summary)
    rule = None if category else detect_custom_alert_rule(event.summary)
    if category is None and rule is None:
        return None
    trigger_key = category or f"rule:{rule['id']}"
    if category:
        alert_message = f"Faro detectou {FAMILY_ALERT_LABELS[category]}: «{event.summary}»"
        alert_kind = FAMILY_ALERT_KIND.get(category, "hazard")
    else:
        alert_message = f"Faro: {rule['description']}. Conversación: «{event.summary}»"
        alert_kind = "hazard"
    previous = repository.last_auto_alert.get(trigger_key)
    if previous and previous > now() - FAMILY_ALERT_DEDUP:
        return {"alert_category": category or rule["id"], "family_alert_status": "suppressed_recent"}
    contacts = enabled_alert_contacts()
    if not contacts:
        return {"alert_category": category or rule["id"], "family_alert_status": "no_contact"}
    repository.last_auto_alert[trigger_key] = now()
    deliveries, failures = send_alert_to_contacts(contacts, EmergencyAlertCreate(
        kind=alert_kind, spoken_message=alert_message, explicit_help_request=False,
    ))
    status = "sent" if any(delivery.message_id for _, delivery in deliveries) else (
        "test_mode" if deliveries else "failed"
    )
    return {
        "alert_category": category or rule["id"],
        "alert_rule_description": rule["description"] if rule else None,
        "family_alert_status": status,
        "recipients_attempted": len(contacts),
        "recipients_delivered": len(deliveries),
        "recipient_failures": " | ".join(failures[:3]),
    }


def person_or_404(person_id: UUID) -> Person:
    person = repository.people.get(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


def read_images(files: list[UploadFile], required: int) -> list[bytes]:
    if len(files) != required:
        raise HTTPException(status_code=422, detail=f"Exactly {required} face images are required")
    images = []
    for file in files:
        if file.content_type not in {"image/jpeg", "image/png"}:
            raise HTTPException(status_code=415, detail="Only JPEG or PNG images are accepted")
        data = file.file.read()
        if not data or len(data) > 15_000_000:
            raise HTTPException(status_code=422, detail="Each image must be between 1 byte and 15 MB")
        images.append(data)
    return images


def read_face_images(files: list[UploadFile], minimum: int = 1, maximum: int = 5) -> list[bytes]:
    if not minimum <= len(files) <= maximum:
        raise HTTPException(
            status_code=422, detail=f"Between {minimum} and {maximum} face images are required"
        )
    images = []
    for file in files:
        if file.content_type not in {"image/jpeg", "image/png"}:
            raise HTTPException(status_code=415, detail="Only JPEG or PNG images are accepted")
        data = file.file.read()
        if not data or len(data) > 15_000_000:
            raise HTTPException(status_code=422, detail="Each image must be between 1 byte and 15 MB")
        images.append(data)
    return images


def record_usage(actor: str) -> None:
    """Meter provider cost for product economics; it never limits normal customer use."""
    repository.recognition_times[actor].append(now())


def decide(candidates: list[FaceCandidate]) -> tuple[Optional[UUID], Optional[float], str]:
    eligible = [candidate for candidate in candidates if candidate.confidence >= CONFIDENCE_MINIMUM]
    if not eligible:
        return None, None, "No candidate met the confidence threshold"
    person_id, count = Counter(candidate.person_id for candidate in eligible).most_common(1)[0]
    scores = [candidate.confidence for candidate in eligible if candidate.person_id == person_id]
    mean = sum(scores) / len(scores)
    if count < CONSENSUS_MINIMUM or mean < CONFIDENCE_MEAN_MINIMUM:
        return None, mean, "At least two agreeing frames at 95% confidence are required"
    return person_id, mean, "Confirmed by conservative multi-frame consensus"


@app.get("/", include_in_schema=False)
def caregiver_portal() -> FileResponse:
    return FileResponse(web_dir / "index.html")


downloads_dir = web_dir.parent / "downloads"


@app.get("/download/faro.apk", include_in_schema=False)
def download_faro_app() -> FileResponse:
    apk = downloads_dir / "faro.apk"
    if not apk.is_file():
        raise HTTPException(status_code=404, detail="La aplicación todavía no está disponible para descarga")
    return FileResponse(
        apk, media_type="application/vnd.android.package-archive", filename="Faro.apk"
    )


WEB_DOWNLOADS_DIR = web_dir / "downloads"


def _download_apk(filename: str, download_name: str) -> FileResponse:
    apk = WEB_DOWNLOADS_DIR / filename
    if not apk.is_file():
        raise HTTPException(status_code=404, detail="La aplicación todavía no está disponible para descarga")
    return FileResponse(
        apk, media_type="application/vnd.android.package-archive", filename=download_name
    )


@app.get("/download/camera-access.apk", include_in_schema=False)
def download_camera_access_app() -> FileResponse:
    return _download_apk("camera-access.apk", "Faro-Camara.apk")


@app.get("/download/faro-movil.apk", include_in_schema=False)
def download_faro_movil_app() -> FileResponse:
    return _download_apk("faro-movil.apk", "Faro-Movil.apk")


@app.get("/download/faro-familia.apk", include_in_schema=False)
def download_faro_familia_app() -> FileResponse:
    return _download_apk("faro-familia.apk", "Faro-Familia.apk")


TWA_ASSET_LINKS = [{
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
        "namespace": "android_app",
        "package_name": os.getenv("AURA_TWA_PACKAGE", "com.farodamemoria.familia"),
        "sha256_cert_fingerprints": [
            os.getenv(
                "AURA_TWA_SHA256",
                "82:F0:DB:14:BC:D0:14:22:7F:CE:49:4B:8E:A9:00:E6:03:C6:84:6B:E9:D4:0E:70:9E:A8:4F:63:D2:16:03:98",
            )
        ],
    },
}]


@app.get("/.well-known/assetlinks.json", include_in_schema=False)
def asset_links() -> Response:
    return Response(content=json.dumps(TWA_ASSET_LINKS), media_type="application/json")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "aura-backend", "face_provider": type(face_provider).__name__, "alert_provider": type(alert_provider).__name__, "api_version": API_VERSION}


@app.get("/v1/version")
def version() -> dict[str, object]:
    return {
        "api_version": API_VERSION,
        "features": {
            "onboarding": True,
            "events": True,
            "location_tracking": True,
            "protective_observations": True,
            "family_alerts": True,
            "separate_patient_profile": True,
            "care_network_management": True,
            "family_conversation": True,
            "family_ai": bool(os.getenv("AURA_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")),
        },
    }


@app.get("/v1/account", response_model=AccountSummary)
def account_summary(authorization: Optional[str] = Header(default=None)) -> AccountSummary:
    actor = require_auth(authorization)
    return AccountSummary(account_id=actor, plan=os.getenv("AURA_PLAN", "faro"), status="active")


@app.put("/v1/care-contact", response_model=CareContact)
def configure_care_contact(request: CareContactCreate, authorization: Optional[str] = Header(default=None)) -> CareContact:
    require_auth(authorization)
    if not request.whatsapp_consent:
        raise HTTPException(status_code=422, detail="WhatsApp consent is required")
    if request.known_person_id is not None:
        person_or_404(request.known_person_id)
    existing = next((item for item in repository.care_contacts.values() if item.phone_e164 == request.phone_e164), None)
    contact = (
        CareContact.model_validate({**existing.model_dump(), **request.model_dump()}) if existing
        else CareContact(id=uuid4(), created_at=now(), **request.model_dump())
    )
    repository.care_contacts[contact.id] = contact
    repository.save_care_contacts()
    return contact


@app.get("/v1/care-contact", response_model=Optional[CareContact])
def get_care_contact(authorization: Optional[str] = Header(default=None)) -> Optional[CareContact]:
    require_auth(authorization)
    return next(iter(repository.care_contacts.values()), None)


@app.get("/v1/care-contacts", response_model=list[CareContact])
def list_care_contacts(authorization: Optional[str] = Header(default=None)) -> list[CareContact]:
    require_auth(authorization)
    return sorted(repository.care_contacts.values(), key=lambda contact: (contact.priority, contact.display_name.lower()))


@app.post("/v1/care-contacts", response_model=CareContact, status_code=201)
def create_care_contact(request: CareContactCreate, authorization: Optional[str] = Header(default=None)) -> CareContact:
    require_auth(authorization)
    if not request.whatsapp_consent:
        raise HTTPException(status_code=422, detail="WhatsApp consent is required")
    if request.known_person_id is not None:
        person_or_404(request.known_person_id)
    normalized_phone = request.phone_e164
    if any(contact.phone_e164 == normalized_phone for contact in repository.care_contacts.values()):
        raise HTTPException(status_code=409, detail="This phone is already in the care network")
    contact = CareContact(id=uuid4(), created_at=now(), **request.model_dump())
    repository.care_contacts[contact.id] = contact
    repository.save_care_contacts()
    repository.add_event(EventCreate(
        kind="caregiver_action", summary=f"{contact.display_name} añadido a la red de cuidados",
        source="portal", metadata={"contact_id": str(contact.id), "role": contact.role},
    ))
    return contact


@app.patch("/v1/care-contacts/{contact_id}", response_model=CareContact)
def update_care_contact(
    contact_id: UUID, request: CareContactUpdate,
    authorization: Optional[str] = Header(default=None),
) -> CareContact:
    require_auth(authorization)
    contact = repository.care_contacts.get(contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Care contact not found")
    changes = request.model_dump(exclude_unset=True)
    if request.known_person_id is not None:
        person_or_404(request.known_person_id)
    phone = changes.get("phone_e164")
    if phone and any(existing.id != contact_id and existing.phone_e164 == phone for existing in repository.care_contacts.values()):
        raise HTTPException(status_code=409, detail="This phone is already in the care network")
    updated = CareContact.model_validate({**contact.model_dump(), **changes})
    repository.care_contacts[contact_id] = updated
    repository.save_care_contacts()
    return updated


@app.delete("/v1/care-contacts/{contact_id}", status_code=204)
def delete_care_contact(contact_id: UUID, authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    if contact_id not in repository.care_contacts:
        raise HTTPException(status_code=404, detail="Care contact not found")
    del repository.care_contacts[contact_id]
    repository.save_care_contacts()
    return Response(status_code=204)


@app.get("/v1/patient-profile", response_model=Optional[CaredPersonProfile])
def get_patient_profile(authorization: Optional[str] = Header(default=None)) -> Optional[CaredPersonProfile]:
    require_auth(authorization)
    return repository.get_patient_profile()


@app.put("/v1/patient-profile", response_model=CaredPersonProfile)
def update_patient_profile(
    request: CaredPersonProfile, authorization: Optional[str] = Header(default=None),
) -> CaredPersonProfile:
    require_auth(authorization)
    current = repository.get_patient_profile()
    if current is not None:
        request = request.model_copy(update={
            "face_enrollment_samples": current.face_enrollment_samples,
            "face_enrollment_complete": current.face_enrollment_complete,
            "profile_photo_available": current.profile_photo_available,
        })
    repository.save_patient_profile(request)
    repository.add_event(EventCreate(
        kind="caregiver_action", summary="Ficha del paciente actualizada", source="portal",
        metadata={"patient_profile": True},
    ))
    return request


def distance_meters(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    radius = 6_371_000.0
    phi_a, phi_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    haversine = math.sin(delta_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


@app.post("/v1/location/answer", response_model=LocationAnswer)
def answer_location_question(
    request: LocationQuestion,
    authorization: Optional[str] = Header(default=None),
) -> LocationAnswer:
    require_auth(authorization)
    if request.recorded_at and now() - request.recorded_at > timedelta(minutes=5):
        return LocationAnswer(
            status="refresh_required",
            message="Estoy actualizando tu ubicación para poder decírtelo con seguridad.",
            accuracy_meters=request.accuracy_meters,
        )
    profile = repository.get_patient_profile()
    home = profile.home_address if profile else None
    if home and home.latitude is not None and home.longitude is not None:
        distance = distance_meters(request.latitude, request.longitude, home.latitude, home.longitude)
        home_margin = max(35.0, min(request.accuracy_meters, 150.0))
        if distance <= home_margin:
            return LocationAnswer(
                status="at_home",
                message="Estás en casa.",
                place_label=home.label() or "Casa",
                distance_meters=round(distance, 1),
                accuracy_meters=request.accuracy_meters,
            )
    if request.accuracy_meters > 150:
        return LocationAnswer(
            status="refresh_required",
            message="La ubicación todavía es aproximada. Estoy intentando afinarla.",
            accuracy_meters=request.accuracy_meters,
        )
    return LocationAnswer(
        status="coordinates_available",
        message="No parece que estés en casa. Puedo compartir tu ubicación con tu familiar o cuidador.",
        distance_meters=(round(distance, 1) if home and home.latitude is not None and home.longitude is not None else None),
        accuracy_meters=request.accuracy_meters,
    )


@app.get("/v1/patient-profile/photo", response_class=Response)
def get_patient_profile_photo(authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    profile = repository.get_patient_profile()
    photo = repository.person_photo(PATIENT_FACE_ID)
    if profile is None or not profile.profile_photo_available or photo is None:
        raise HTTPException(status_code=404, detail="Patient profile photo is unavailable")
    image, media_type = photo
    return Response(content=image, media_type=media_type, headers={"Cache-Control": "no-store, private"})


@app.get("/v1/patient-profile/face-samples/{sample_index}", response_class=Response)
def get_patient_face_sample(sample_index: int, authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    if sample_index < 1 or sample_index > 5:
        raise HTTPException(status_code=404, detail="Patient face sample is unavailable")
    photo = repository.person_photo_sample(PATIENT_FACE_ID, sample_index)
    if photo is None:
        raise HTTPException(status_code=404, detail="Patient face sample is unavailable")
    image, media_type = photo
    return Response(content=image, media_type=media_type, headers={"Cache-Control": "no-store, private"})


@app.post("/v1/patient-profile/face-samples", response_model=CaredPersonProfile)
def enroll_patient_face_samples(
    files: Annotated[list[UploadFile], File()],
    authorization: Optional[str] = Header(default=None),
) -> CaredPersonProfile:
    require_auth(authorization)
    profile = repository.get_patient_profile()
    if profile is None:
        raise HTTPException(status_code=409, detail="Save the patient profile before adding photos")
    images = read_images(files, required=5)
    face_provider.delete(PATIENT_FACE_ID)
    indexed = face_provider.enroll(PATIENT_FACE_ID, images)
    if indexed != 5:
        face_provider.delete(PATIENT_FACE_ID)
        raise HTTPException(
            status_code=422,
            detail="No se reconoce bien tu cara en todas las fotos. Usa imágenes de frente, con buena luz y sin que la cara quede cortada.",
        )
    photos_saved = repository.save_person_photos(PATIENT_FACE_ID, images)
    updated = profile.model_copy(update={
        "face_enrollment_samples": indexed,
        "face_enrollment_complete": True,
        "profile_photo_available": photos_saved == 5,
    })
    repository.save_patient_profile(updated)
    return updated


@app.put("/v1/onboarding", response_model=OnboardingConfiguration)
def configure_onboarding(request: OnboardingCreate, authorization: Optional[str] = Header(default=None)) -> OnboardingConfiguration:
    require_auth(authorization)
    if not request.data_processing_consent:
        raise HTTPException(status_code=422, detail="Data processing consent is required")
    if not any(contact.whatsapp_consent and contact.alerts_enabled for contact in request.family_contacts):
        raise HTTPException(status_code=422, detail="At least one authorized family alert contact is required")
    contacts = [CareContact(id=uuid4(), created_at=now(), **item.model_dump()) for item in request.family_contacts]
    configuration = OnboardingConfiguration(
        cared_person=request.cared_person, family_contacts=contacts,
        data_processing_consent=True, configured_at=now(),
    )
    repository.care_contacts = {contact.id: contact for contact in contacts}
    repository.save_care_contacts()
    repository.save_onboarding(configuration)
    repository.save_patient_profile(request.cared_person)
    repository.add_event(EventCreate(
        kind="caregiver_action", summary="Configuración inicial completada",
        source="portal", metadata={"family_contacts": len(contacts)},
    ))
    return configuration


@app.get("/v1/onboarding", response_model=Optional[OnboardingConfiguration])
def get_onboarding(authorization: Optional[str] = Header(default=None)) -> Optional[OnboardingConfiguration]:
    require_auth(authorization)
    return repository.get_onboarding()


@app.post("/v1/emergency-alerts", response_model=EmergencyAlert, status_code=201)
def create_emergency_alert(request: EmergencyAlertSubmission, authorization: Optional[str] = Header(default=None)) -> EmergencyAlert:
    actor = require_auth(authorization)
    if not request.explicit_help_request:
        raise HTTPException(status_code=422, detail="An explicit help request is required")
    contacts = enabled_alert_contacts()
    if not contacts:
        raise HTTPException(status_code=409, detail="No family WhatsApp contact is configured")
    deduplication_key = f"{actor}:{request.kind}"
    previous = repository.last_emergency_at.get(deduplication_key)
    if previous and previous > now() - EMERGENCY_ALERT_COOLDOWN:
        raise HTTPException(status_code=409, detail="A similar alert was already created recently")
    repository.last_emergency_at[deduplication_key] = now()
    alert_request = EmergencyAlertCreate.model_validate(request.model_dump(exclude={
        "evidence_image_base64", "evidence_mime_type", "evidence_captured_at",
    }))
    image, photo_status = decode_recent_evidence_fields(
        request.evidence_image_base64, request.evidence_mime_type, request.evidence_captured_at,
    )
    draft = EmergencyAlert(id=uuid4(), created_at=now(), delivery_status="pending", **alert_request.model_dump())
    deliveries, failures = send_alert_to_contacts(contacts, alert_request, image=image)
    if not deliveries:
        delivery_status, message_id = "failed", None
        draft = draft.model_copy(update={"delivery_status": delivery_status})
        repository.emergency_alerts[draft.id] = draft
        raise HTTPException(status_code=502, detail="The family alert could not be delivered")
    message_id = next((delivery.message_id for _, delivery in deliveries if delivery.message_id), None)
    delivery_status = "sent" if message_id else "test_mode"
    if image is not None:
        statuses = [delivery.photo_status for _, delivery in deliveries]
        photo_status = "sent" if "sent" in statuses else statuses[0]
    alert = draft.model_copy(update={"delivery_status": delivery_status, "provider_message_id": message_id})
    repository.emergency_alerts[alert.id] = alert
    repository.add_event(EventCreate(
        kind="help_request" if request.kind == "episode" else "location",
        summary=request.spoken_message, source="glasses", severity="urgent",
        latitude=request.latitude, longitude=request.longitude,
        metadata={"alert_id": str(alert.id), "delivery_status": delivery_status,
                  "photo_delivery_status": photo_status,
                  "location_included": request.latitude is not None and request.longitude is not None,
                  "location_approximate": request.latitude is not None and (
                      request.location_accuracy_meters is None
                      or request.location_accuracy_meters > LOCATION_APPROXIMATE_METERS),
                  "location_accuracy_meters": request.location_accuracy_meters,
                  "location_source": request.location_source,
                  "location_recorded_at": (request.location_recorded_at.isoformat()
                                           if request.location_recorded_at else None),
                  "recipients_attempted": len(contacts), "recipients_delivered": len(deliveries),
                  "recipient_roles": ",".join(contact.role for contact, _ in deliveries),
                  "recipient_failures": len(failures)},
    ))
    return alert


class VoiceIntentResult(BaseModel):
    matched: bool
    transcript: str
    alert_status: Optional[str] = None


def transcribe_audio(data: bytes, filename: str = "command.wav") -> Optional[str]:
    """Transcribe a short glasses-audio clip with OpenAI (es/gl) using multipart."""
    api_key = os.getenv("AURA_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    boundary = "----faro" + uuid4().hex
    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    add_field("model", os.getenv("AURA_TRANSCRIBE_MODEL", "whisper-1"))
    add_field("language", os.getenv("AURA_TRANSCRIBE_LANGUAGE", "es"))
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(data)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=b"".join(parts),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8")).get("text")


@app.post("/v1/voice/intent", response_model=VoiceIntentResult)
async def voice_intent(
    audio: Annotated[UploadFile, File()],
    peak: Annotated[float, Form()] = 0.0,
    loud_ms: Annotated[float, Form()] = 0.0,
    authorization: Optional[str] = Header(default=None),
) -> VoiceIntentResult:
    """Recibe audio de las gafas, lo transcribe y avisa si el paciente se ha perdido."""
    require_auth(authorization)
    data = await audio.read()
    if not data or len(data) > 6_000_000:
        raise HTTPException(status_code=422, detail="Invalid audio clip")
    try:
        transcript = transcribe_audio(data, audio.filename or "command.wav")
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        transcript = None
    if not transcript:
        return VoiceIntentResult(matched=False, transcript="")
    awaiting = None
    for exercise in repository.cognitive_exercises.values():
        if (
            exercise.status == "pending" and exercise.asked_at is not None
            and exercise.patient_answer is None and exercise.asked_at > now() - timedelta(minutes=5)
        ) and (awaiting is None or exercise.asked_at > awaiting.asked_at):
            awaiting = exercise
    if awaiting is not None:
        repository.cognitive_exercises[awaiting.id] = awaiting.model_copy(
            update={"patient_answer": transcript}
        )
        repository.save_cognitive_exercises()
        return VoiceIntentResult(matched=False, transcript=transcript)
    matched = is_lost_request(transcript)
    normalized = normalize_text(transcript)
    is_cough = bool(re.search(r"\b(cof+|cough\w*|tos|tose|toseu|tosido|tosida)\b", normalized))
    if not matched and not is_cough and not (peak >= 4000 and loud_ms <= 350):
        return VoiceIntentResult(matched=False, transcript=transcript)
    if matched:
        kind = "lost"
        message = "Faro: o paciente di estar perdido ou desorientado."
        summary = f"Petición de ayuda por voz: {transcript}"
    elif is_cough:
        kind = "episode"
        message = "Faro: detectáronse episodios de tos."
        summary = "Se detectaron episodios de tos"
    else:
        kind = "hazard"
        message = "Faro: posible caída ou golpe forte detectado."
        summary = "Posible caída o golpe fuerte detectado"
    alert_status = None
    contacts = enabled_alert_contacts()
    if contacts:
        alert = EmergencyAlertCreate(kind=kind, spoken_message=message, explicit_help_request=True)
        deliveries, _ = send_alert_to_contacts(contacts, alert)
        alert_status = "sent" if any(delivery.message_id for _, delivery in deliveries) else "test_mode"
    else:
        alert_status = "no_contact"
    repository.add_event(EventCreate(
        kind="help_request" if matched else "hazard",
        summary=summary,
        source="glasses", severity="urgent",
        metadata={"transcript": transcript, "delivery_status": alert_status},
    ))
    return VoiceIntentResult(matched=True, transcript=transcript, alert_status=alert_status)


@app.get("/v1/emergency-alerts", response_model=list[EmergencyAlert])
def list_emergency_alerts(authorization: Optional[str] = Header(default=None)) -> list[EmergencyAlert]:
    require_auth(authorization)
    return sorted(repository.emergency_alerts.values(), key=lambda item: item.created_at, reverse=True)


@app.post("/v1/admin/reset-cooldowns")
def reset_cooldowns(authorization: Optional[str] = Header(default=None)) -> dict:
    """Limpia los anti-repetición en memoria (reconocimiento, revisiones y avisos).

    Pensado para demos/pruebas: permite volver a anunciar a la misma persona sin esperar.
    """
    require_auth(authorization)
    cleared = len(repository.last_outcome)
    repository.last_outcome.clear()
    repository.last_review_created.clear()
    repository.last_emergency_at.clear()
    return {"status": "ok", "cleared": cleared}


@app.post("/v1/alerts/test")
def test_family_alert(authorization: Optional[str] = Header(default=None)) -> dict:
    """Send a test WhatsApp alert to the care network and report the provider result."""
    require_auth(authorization)
    contacts = enabled_alert_contacts()
    if not contacts:
        raise HTTPException(status_code=409, detail="No hay contactos de cuidado con WhatsApp activado")
    deliveries, failures = send_alert_to_contacts(contacts, EmergencyAlertCreate(
        kind="hazard", spoken_message="Prueba de aviso de Faro da Memoria.", explicit_help_request=False,
    ))
    return {
        "provider": type(alert_provider).__name__,
        "contacts": len(contacts),
        "delivered": [
            {"name": contact.display_name, "message_id": delivery.message_id,
             "channel": delivery.channel, "template_error": delivery.template_error}
            for contact, delivery in deliveries
        ],
        "failures": failures,
    }


WHATSAPP_VERIFY_TOKEN = os.getenv("AURA_WHATSAPP_VERIFY_TOKEN", "faro-whatsapp-verify")


@app.get("/v1/whatsapp/webhook", include_in_schema=False)
def whatsapp_webhook_verify(request: Request) -> Response:
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == WHATSAPP_VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Invalid verify token")


@app.post("/v1/whatsapp/webhook", include_in_schema=False)
async def whatsapp_webhook(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for status_item in value.get("statuses", []) or []:
                repository.record_whatsapp_status(
                    wamid=str(status_item.get("id", "")),
                    status=str(status_item.get("status", "")),
                    recipient=str(status_item.get("recipient_id", "")),
                    errors=json.dumps(status_item.get("errors", []), ensure_ascii=False),
                )
    return {"status": "ok"}


@app.get("/v1/whatsapp/statuses")
def list_whatsapp_statuses(limit: int = 50, authorization: Optional[str] = Header(default=None)) -> list[dict]:
    require_auth(authorization)
    bounded = min(max(limit, 1), 200)
    rows = repository.event_db.execute(
        "SELECT wamid, status, recipient, errors, updated_at FROM whatsapp_status ORDER BY updated_at DESC LIMIT ?",
        (bounded,),
    ).fetchall()
    return [dict(row) for row in rows]


def refresh_location_session(session: LocationSession) -> LocationSession:
    if session.status == "active" and session.expires_at <= now():
        session = session.model_copy(update={"status": "expired"})
        repository.location_sessions[session.id] = session
        repository.save_location_sessions()
    return session


@app.post("/v1/location-sessions", response_model=LocationSession, status_code=201)
def create_location_session(
    request: LocationSessionCreate,
    authorization: Optional[str] = Header(default=None),
) -> LocationSession:
    require_auth(authorization)
    if not request.explicit_help_request and not request.automatic_hazard:
        raise HTTPException(status_code=422, detail="An explicit help request or confirmed automatic hazard is required")
    for existing in repository.location_sessions.values():
        current = refresh_location_session(existing)
        if current.status == "active":
            return current
    session = LocationSession(
        id=uuid4(), share_token=secrets.token_urlsafe(24), created_at=now(),
        expires_at=now() + timedelta(minutes=request.duration_minutes), status="active",
    )
    repository.location_sessions[session.id] = session
    repository.save_location_sessions()
    repository.add_event(EventCreate(
        kind="location",
        summary=("Seguimiento de ubicación iniciado por una investigación de seguridad"
                 if request.automatic_hazard else "Seguimiento de ubicación iniciado a petición de la persona"),
        source="phone", severity="urgent", metadata={"session_id": str(session.id)},
    ))
    return session


@app.put("/v1/location-sessions/{session_id}/location", response_model=LocationSession)
def update_location_session(
    session_id: UUID,
    point: LocationPoint,
    authorization: Optional[str] = Header(default=None),
) -> LocationSession:
    require_auth(authorization)
    session = repository.location_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Location session not found")
    session = refresh_location_session(session)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Location session is no longer active")
    normalized = point.model_copy(update={"recorded_at": point.recorded_at or now()})
    if not prefer_location(normalized, session.last_location):
        return session
    session = session.model_copy(update={"last_location": normalized})
    repository.location_sessions[session.id] = session
    repository.save_location_sessions()
    handle_safe_zone_alert(normalized.latitude, normalized.longitude, normalized.accuracy_meters, source="phone")
    return session


@app.get("/v1/location-sessions/active", response_model=Optional[LocationSession])
def get_active_location_session(authorization: Optional[str] = Header(default=None)) -> Optional[LocationSession]:
    require_auth(authorization)
    active = [refresh_location_session(item) for item in repository.location_sessions.values()]
    return next((item for item in active if item.status == "active"), None)


@app.post("/v1/location-sessions/{session_id}/stop", response_model=LocationSession)
def stop_location_session(
    session_id: UUID,
    authorization: Optional[str] = Header(default=None),
) -> LocationSession:
    require_auth(authorization)
    session = repository.location_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Location session not found")
    session = session.model_copy(update={"status": "stopped"})
    repository.location_sessions[session.id] = session
    repository.save_location_sessions()
    return session


SAFE_ZONE_ALERT_DEDUP = timedelta(minutes=15)
SAFE_ZONE_ACCURACY_MARGIN = 50.0


def patient_name_label() -> str:
    profile = repository.get_patient_profile()
    if profile and profile.preferred_name:
        return profile.preferred_name
    return "La persona cuidada"


def safe_zone_evaluation(
    latitude: float, longitude: float, accuracy_meters: Optional[float],
) -> Optional[tuple[str, Optional[SafeZone], float]]:
    zones = [zone for zone in repository.safe_zones.values() if zone.enabled]
    if not zones:
        return None
    margin = max(0.0, min(accuracy_meters or 0.0, SAFE_ZONE_ACCURACY_MARGIN))
    nearest_zone: Optional[SafeZone] = None
    nearest_distance = 0.0
    for zone in zones:
        distance = distance_meters(latitude, longitude, zone.latitude, zone.longitude)
        if distance <= zone.radius_meters + margin:
            return "inside", zone, round(distance, 1)
        if nearest_zone is None or distance < nearest_distance:
            nearest_zone, nearest_distance = zone, distance
    return "outside", nearest_zone, round(nearest_distance, 1)


def handle_safe_zone_alert(
    latitude: float, longitude: float, accuracy_meters: Optional[float], source: str = "phone",
) -> tuple[str, Optional[str]]:
    """Evalua las zonas seguras y, si esta fuera, avisa una vez a la red de cuidados."""
    evaluation = safe_zone_evaluation(latitude, longitude, accuracy_meters)
    if evaluation is None:
        return "no_zones", None
    status, zone, distance = evaluation
    if status == "inside":
        repository.last_auto_alert.pop("safe_zone", None)
        return "inside", None
    previous = repository.last_auto_alert.get("safe_zone")
    if previous and previous > now() - SAFE_ZONE_ALERT_DEDUP:
        return "outside", None
    repository.last_auto_alert["safe_zone"] = now()
    where = f" a {distance:.0f} m de {zone.name}" if zone else ""
    message = (
        f"Faro: {patient_name_label()} puede estar desorientado; "
        f"esta fuera de las zonas seguras{where}."
    )
    contacts = enabled_alert_contacts()
    if contacts:
        deliveries, _ = send_alert_to_contacts(contacts, EmergencyAlertCreate(
            kind="lost", spoken_message=message, explicit_help_request=False,
            latitude=latitude, longitude=longitude,
        ))
        family_alert_status = (
            "sent" if any(delivery.message_id for _, delivery in deliveries)
            else "test_mode" if deliveries else "failed"
        )
    else:
        family_alert_status = "no_contact"
    repository.add_event(EventCreate(
        kind="location", source=source, severity="attention", summary=message,
        latitude=latitude, longitude=longitude,
        metadata={"hazard": "safe_zone", "zone_id": str(zone.id) if zone else "",
                  "distance_meters": distance, "family_alert_status": family_alert_status},
    ))
    return "outside", family_alert_status


@app.post("/v1/safe-zones", response_model=SafeZone, status_code=201)
def create_safe_zone(request: SafeZoneCreate, authorization: Optional[str] = Header(default=None)) -> SafeZone:
    require_auth(authorization)
    zone = SafeZone(id=uuid4(), created_at=now(), **request.model_dump())
    repository.safe_zones[zone.id] = zone
    repository.save_safe_zones()
    return zone


@app.get("/v1/safe-zones", response_model=list[SafeZone])
def list_safe_zones(authorization: Optional[str] = Header(default=None)) -> list[SafeZone]:
    require_auth(authorization)
    return sorted(repository.safe_zones.values(), key=lambda zone: zone.created_at)


@app.patch("/v1/safe-zones/{zone_id}", response_model=SafeZone)
def update_safe_zone(
    zone_id: UUID, request: SafeZoneUpdate, authorization: Optional[str] = Header(default=None),
) -> SafeZone:
    require_auth(authorization)
    zone = repository.safe_zones.get(zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Safe zone not found")
    updated = zone.model_copy(update=request.model_dump(exclude_unset=True))
    repository.safe_zones[zone_id] = updated
    repository.save_safe_zones()
    return updated


@app.delete("/v1/safe-zones/{zone_id}", status_code=204, response_class=Response)
def delete_safe_zone(zone_id: UUID, authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    repository.safe_zones.pop(zone_id, None)
    repository.save_safe_zones()
    return Response(status_code=204)


@app.post("/v1/safe-zones/check", response_model=SafeZoneStatus)
def check_safe_zone(request: SafeZoneCheck, authorization: Optional[str] = Header(default=None)) -> SafeZoneStatus:
    require_auth(authorization)
    evaluation = safe_zone_evaluation(request.latitude, request.longitude, request.accuracy_meters)
    if evaluation is None:
        return SafeZoneStatus(status="no_zones", message="Todavia no hay zonas seguras configuradas.")
    status, zone, distance = evaluation
    if status == "inside":
        repository.last_auto_alert.pop("safe_zone", None)
        name = zone.name if zone else "la zona segura"
        return SafeZoneStatus(
            status="inside", zone=zone, distance_meters=distance,
            message=f"Dentro de {name}. Todo en orden.",
        )
    _, family_alert_status = handle_safe_zone_alert(
        request.latitude, request.longitude, request.accuracy_meters, source="phone",
    )
    where = f" (a {distance:.0f} m de {zone.name})" if zone else ""
    return SafeZoneStatus(
        status="outside", zone=zone, distance_meters=distance,
        message=f"Fuera de las zonas seguras{where}. Se avisa a la familia.",
        family_alert_status=family_alert_status,
    )


@app.get("/v1/location-share/{share_token}", response_model=LocationSession)
def shared_location(share_token: str) -> LocationSession:
    session = next((item for item in repository.location_sessions.values() if secrets.compare_digest(item.share_token, share_token)), None)
    if session is None:
        raise HTTPException(status_code=404, detail="Location link is invalid")
    session = refresh_location_session(session)
    if session.status == "expired":
        raise HTTPException(status_code=410, detail="Location link has expired")
    return session


def active_alert_location() -> tuple[Optional[LocationPoint], Optional[str]]:
    candidates = [refresh_location_session(item) for item in repository.location_sessions.values()]
    active = sorted((item for item in candidates if item.status == "active" and item.last_location),
                    key=lambda item: item.last_location.recorded_at or item.created_at, reverse=True)
    if not active:
        return None, None
    session = active[0]
    point = session.last_location
    recorded_at = point.recorded_at or session.created_at
    if recorded_at < now() - LOCATION_MAX_AGE:
        return None, None
    public_base = os.getenv("AURA_PUBLIC_BASE_URL", "https://d2n7ih9kfxbzvd.cloudfront.net").rstrip("/")
    return point, f"{public_base}/track/{session.share_token}"


def decode_recent_evidence_fields(encoded: Optional[str], mime_type: Optional[str],
                                  captured_at: Optional[datetime]) -> tuple[Optional[bytes], str]:
    if not encoded:
        return None, "missing"
    if mime_type != "image/jpeg" or captured_at is None:
        return None, "invalid"
    age = now() - captured_at
    if age < timedelta(seconds=-5) or age > timedelta(seconds=20):
        return None, "expired"
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None, "invalid"
    if not image or len(image) > 5_000_000 or not image.startswith(b"\xff\xd8"):
        return None, "invalid"
    return image, "ready"


def decode_recent_evidence(request: ProtectiveObservationCreate) -> tuple[Optional[bytes], str]:
    return decode_recent_evidence_fields(
        request.evidence_image_base64, request.evidence_mime_type, request.evidence_captured_at,
    )


@app.post("/v1/protective-observations", response_model=ProtectiveObservationDecision)
def record_protective_observation(
    request: ProtectiveObservationCreate,
    authorization: Optional[str] = Header(default=None),
) -> ProtectiveObservationDecision:
    require_auth(authorization)
    observed_at = request.observed_at or now()
    sample = request.model_copy(update={
        "observed_at": observed_at,
        "evidence_image_base64": None,
        "evidence_mime_type": None,
        "evidence_captured_at": None,
    })
    window = repository.protective_observations[request.kind]
    window.append(sample)
    while window and (observed_at - (window[0].observed_at or observed_at)) > timedelta(seconds=45):
        window.popleft()
    reliable = [item for item in window if item.observed and item.confidence >= 0.85]
    if not request.observed:
        window.clear()
        return ProtectiveObservationDecision(action="none", consecutive_observations=0)
    if request.kind == "keys_location" and request.confidence >= 0.9 and request.location_label:
        object_memory = ObjectMemory(
            id=uuid4(), object_name="llaves", place=request.location_label,
            description=request.description, confidence=request.confidence, source="glasses",
            seen_at=observed_at, created_at=now(),
        )
        repository.object_memories[object_memory.id] = object_memory
        repository.save_object_memories()
        repository.add_event(EventCreate(
            kind="object_location", summary=f"Las llaves se vieron en {request.location_label}",
            source="glasses", metadata={"object": "keys", "location": request.location_label,
                                        "confidence": request.confidence},
        ))
        return ProtectiveObservationDecision(
            action="remember", message=f"Recordé que las llaves están en {request.location_label}",
            consecutive_observations=1,
        )
    required = 3 if request.kind in {"cookware_heating", "water_running", "smoke_or_fire", "broken_glass", "dangerous_impact"} else 4
    if len(reliable) < required:
        return ProtectiveObservationDecision(action="none", consecutive_observations=len(reliable))
    previous = repository.last_protective_action.get(request.kind)
    if previous and previous > observed_at - timedelta(minutes=5):
        return ProtectiveObservationDecision(action="none", consecutive_observations=len(reliable))
    repository.last_protective_action[request.kind] = observed_at
    if request.kind == "fridge_open":
        action, message, severity = "remind", "A neveira parece levar un anaco aberta. Queres pechala?", "attention"
    elif request.kind == "door_open":
        action, message, severity = "remind", "A porta parece quedar aberta. Queres comprobala?", "attention"
    elif request.kind == "water_running":
        action, message, severity = "warn", "Parece que a auga segue correndo. Imos pechala con calma.", "urgent"
    elif request.kind == "smoke_or_fire":
        action, message, severity = "warn", "Vexo sinais de lume ou fume. Imos afastarnos con calma e pedir axuda.", "urgent"
    elif request.kind == "broken_glass":
        action, message, severity = "warn", "Parece que hai cristais rotos. Non te achegues; imos pedir axuda.", "urgent"
    elif request.kind == "dangerous_impact":
        action, message, severity = "warn", "Parece que ocorreu un golpe forte. Queda nun lugar seguro mentres pedimos axuda.", "urgent"
    else:
        action, message, severity = "warn", "Parece que quedou algo quentando no lume. Imos apagalo con calma.", "urgent"
    family_alert_status = None
    photo_delivery_status = None
    location_included = False
    notified_contact = None
    location = None
    tracking_url = None
    if severity == "urgent":
        contacts = enabled_alert_contacts()
        if not contacts:
            family_alert_status = "no_contact"
        else:
            evidence, photo_delivery_status = decode_recent_evidence(request)
            location, tracking_url = active_alert_location()
            location_included = location is not None
            deliveries, _ = send_alert_to_contacts(contacts, EmergencyAlertCreate(
                kind="hazard", spoken_message=request.description, explicit_help_request=False,
                latitude=location.latitude if location else None,
                longitude=location.longitude if location else None,
                location_accuracy_meters=location.accuracy_meters if location else None,
                location_source=location.source if location else None,
                location_recorded_at=location.recorded_at if location else None,
                tracking_url=tracking_url,
            ), image=evidence)
            notified_contact = ",".join(str(contact.id) for contact, _ in deliveries) or None
            family_alert_status = (
                "sent" if any(delivery.message_id for _, delivery in deliveries)
                else "test_mode" if deliveries else "failed"
            )
            if evidence is not None and deliveries:
                statuses = [delivery.photo_status for _, delivery in deliveries]
                photo_delivery_status = "sent" if "sent" in statuses else statuses[0]
    repository.add_event(EventCreate(
        kind="hazard", summary=request.description, source="glasses", severity=severity,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
        metadata={"hazard": request.kind, "confidence": request.confidence,
                  "observations": len(reliable), "family_alert_status": family_alert_status,
                  "notified_contact_id": notified_contact, "photo_delivery_status": photo_delivery_status,
                  "location_included": location_included,
                  "location_accuracy_meters": location.accuracy_meters if location else None,
                  "location_source": location.source if location else None,
                  "location_approximate": location is not None and (
                      location.accuracy_meters is None
                      or location.accuracy_meters > LOCATION_APPROXIMATE_METERS)},
    ))
    return ProtectiveObservationDecision(
        action=action, message=message, consecutive_observations=len(reliable),
        family_alert_status=family_alert_status, photo_delivery_status=photo_delivery_status,
        location_included=location_included,
    )


@app.get("/track/{share_token}", response_class=HTMLResponse, include_in_schema=False)
def location_tracking_page(share_token: str) -> HTMLResponse:
    if not share_token or len(share_token) > 100 or not all(char.isalnum() or char in "-_" for char in share_token):
        raise HTTPException(status_code=404, detail="Location link is invalid")
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#17483a">
<title>Ubicación · Faro Familia</title><style>
body{{margin:0;background:#f5f7f2;color:#19332b;font:16px system-ui;display:grid;min-height:100vh;place-items:center}}
main{{width:min(92%,520px);background:white;border-radius:24px;padding:28px;box-shadow:0 18px 60px #19332b1f}}
h1{{font:500 34px Georgia;margin:5px 0}}.mark{{color:#2d7258;font-weight:700}}#map{{display:block;text-align:center;background:#2d7258;color:white;padding:15px;border-radius:12px;text-decoration:none;margin:22px 0}}
.meta{{color:#64736d}}.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#4fc27b;margin-right:7px}}
</style></head><body><main><span class="mark">Faro Familia</span><h1>Ubicación compartida</h1>
<p><span class="dot"></span><span id="state">Buscando la ubicación más reciente…</span></p><a id="map" hidden>Abrir en Google Maps</a><p id="details" class="meta"></p><p class="meta">Este enlace temporal se actualiza automáticamente y deja de funcionar al finalizar el seguimiento.</p></main>
<script>const token={json.dumps(share_token)},APPROX={int(LOCATION_APPROXIMATE_METERS)};async function update(){{try{{const r=await fetch('/v1/location-share/'+token);if(!r.ok)throw new Error(r.status===410?'El seguimiento ha finalizado':'Ubicación no disponible');const s=await r.json(),p=s.last_location;if(!p){{state.textContent='Esperando la primera ubicación…';return}}state.textContent=s.status==='active'?'Seguimiento activo':'Seguimiento detenido';map.href=`https://maps.google.com/?q=${{p.latitude}},${{p.longitude}}`;map.hidden=false;const mins=p.recorded_at?Math.max(0,Math.round((Date.now()-new Date(p.recorded_at).getTime())/60000)):0;details.textContent=[mins>=10?'Última posición conocida hace '+mins+' min':'',p.accuracy_meters==null?'':'precisión '+(p.accuracy_meters>APPROX?'aproximada':'precisa')+': ±'+Math.round(p.accuracy_meters)+' m'+(p.source?' ('+p.source+')':''),p.battery_percent==null?'':'batería: '+p.battery_percent+'%'].filter(Boolean).join(' · ')}}catch(e){{state.textContent=e.message;map.hidden=true}}}}update();setInterval(update,10000)</script></body></html>""")


@app.post("/v1/events", response_model=Event, status_code=201)
def create_event(request: EventCreate, authorization: Optional[str] = Header(default=None)) -> Event:
    require_auth(authorization)
    event = repository.add_event(request)
    alert_metadata = maybe_send_family_alert(event)
    if alert_metadata:
        repository.update_event_metadata(event.id, alert_metadata)
        event = event.model_copy(update={"metadata": {**event.metadata, **alert_metadata}})
    return event


@app.delete("/v1/events")
def clear_events(authorization: Optional[str] = Header(default=None)) -> dict:
    """Vacía el historial de la pestaña Memoria."""
    require_auth(authorization)
    return {"deleted": repository.clear_events()}


@app.get("/v1/events", response_model=list[Event])
def list_events(
    limit: int = 100,
    kind: Optional[str] = None,
    authorization: Optional[str] = Header(default=None),
) -> list[Event]:
    require_auth(authorization)
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 500")
    allowed = {"conversation", "episode", "help_request", "location", "recognition", "caregiver_action", "hazard", "object_location", "routine", "system"}
    if kind is not None and kind not in allowed:
        raise HTTPException(status_code=422, detail="Unknown event kind")
    return repository.list_events(limit, kind)


@app.get("/v1/conversation-memory/search", response_model=list[ConversationMemoryMatch])
def search_conversation_memory(
    query: str,
    limit: int = 8,
    authorization: Optional[str] = Header(default=None),
) -> list[ConversationMemoryMatch]:
    require_auth(authorization)
    if len(query.strip()) < 2 or len(query) > 500:
        raise HTTPException(status_code=422, detail="Query must contain between 2 and 500 characters")
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 20")
    return repository.search_conversations(query, limit)


FAMILY_LANGUAGE_FALLBACK = "es"
FAMILY_DAY_LABELS: dict[str, dict] = {
    "es": {
        "empty": "Hoy todavía no hay actividad registrada para el paciente.",
        "header": "Hoy se han registrado {total} acontecimientos.",
        "kinds": {
            "conversation": ("{count} conversación con Faro", "{count} conversaciones con Faro"),
            "recognition": ("{count} reconocimiento de personas", "{count} reconocimientos de personas"),
            "help_request": ("{count} petición de ayuda", "{count} peticiones de ayuda"),
            "hazard": ("{count} aviso preventivo", "{count} avisos preventivos"),
            "episode": ("{count} posible pérdida de memoria", "{count} posibles pérdidas de memoria"),
            "location": ("{count} actualización de ubicación", "{count} actualizaciones de ubicación"),
            "object_location": ("{count} objeto recordado", "{count} objetos recordados"),
            "caregiver_action": ("{count} acción de la familia", "{count} acciones de la familia"),
            "routine": ("{count} rutina", "{count} rutinas"),
            "system": ("{count} aviso del sistema", "{count} avisos del sistema"),
        },
        "recognized": "Se reconoció a {names}.",
        "urgent": "Hay {count} aviso(s) importante(s) que conviene revisar.",
        "closing": "Sin más incidencias destacables.",
        "join": ", ",
        "and": " y ",
    },
    "gl": {
        "empty": "Hoxe aínda non hai actividade rexistrada para o paciente.",
        "header": "Hoxe rexistráronse {total} acontecementos.",
        "kinds": {
            "conversation": ("{count} conversa con Faro", "{count} conversas con Faro"),
            "recognition": ("{count} recoñecemento de persoas", "{count} recoñecementos de persoas"),
            "help_request": ("{count} petición de axuda", "{count} peticións de axuda"),
            "hazard": ("{count} aviso preventivo", "{count} avisos preventivos"),
            "episode": ("{count} posible perda de memoria", "{count} posibles perdas de memoria"),
            "location": ("{count} actualización de localización", "{count} actualizacións de localización"),
            "object_location": ("{count} obxecto recordado", "{count} obxectos recordados"),
            "caregiver_action": ("{count} acción da familia", "{count} accións da familia"),
            "routine": ("{count} rutina", "{count} rutinas"),
            "system": ("{count} aviso do sistema", "{count} avisos do sistema"),
        },
        "recognized": "Recoñeceuse a {names}.",
        "urgent": "Hai {count} aviso(s) importante(s) que convén revisar.",
        "closing": "Sen máis incidencias destacables.",
        "join": ", ",
        "and": " e ",
    },
    "en": {
        "empty": "There is no activity registered for the patient today yet.",
        "header": "{total} events were registered today.",
        "kinds": {
            "conversation": ("{count} conversation with Faro", "{count} conversations with Faro"),
            "recognition": ("{count} person recognised", "{count} people recognised"),
            "help_request": ("{count} help request", "{count} help requests"),
            "hazard": ("{count} preventive warning", "{count} preventive warnings"),
            "episode": ("{count} possible memory lapse", "{count} possible memory lapses"),
            "location": ("{count} location update", "{count} location updates"),
            "object_location": ("{count} remembered object", "{count} remembered objects"),
            "caregiver_action": ("{count} family action", "{count} family actions"),
            "routine": ("{count} routine", "{count} routines"),
            "system": ("{count} system notice", "{count} system notices"),
        },
        "recognized": "Recognised {names}.",
        "urgent": "There are {count} important notice(s) worth reviewing.",
        "closing": "No other notable incidents.",
        "join": ", ",
        "and": " and ",
    },
}
FAMILY_LANGUAGE_NAMES = {"es": "español", "gl": "gallego", "en": "inglés"}
FAMILY_INTENTS: dict[str, set[str]] = {
    "warnings": {"hazard", "help_request", "episode"},
    "recognitions": {"recognition"},
    "conversations": {"conversation"},
    "location": {"location"},
    "objects": {"object_location"},
    "help": {"help_request"},
    "memory": {"episode"},
}
FAMILY_INTENT_KEYWORDS: dict[str, set[str]] = {
    "warnings": {"aviso", "alerta", "alert", "peligro", "perigo", "riesgo", "urxen", "urgen", "inciden", "warning", "danger"},
    "recognitions": {"reconoc", "recoñec", "quien", "quién", "quen", "vio", "viu", "visita", "persona", "people", "recognis", "recogniz"},
    "conversations": {"convers", "conversa", "habl", "fala", "dijo", "dixo", "conto", "contó", "chat", "talk"},
    "location": {"ubicaci", "localiz", "donde", "dónde", "onde", "location", "gps"},
    "objects": {"objeto", "obxecto", "llave", "chave", "gafas", "perdido", "perdeu", "encontr", "object", "keys"},
    "help": {"ayuda", "axuda", "socorro", "help", "auxilio"},
    "memory": {"memoria", "olvid", "esque", "episodio", "desorient", "memory"},
}
FAMILY_FOCUSED_LABELS: dict[str, dict] = {
    "es": {
        "warnings": ("Hoy hay {count} aviso de seguridad:", "Hoy hay {count} avisos de seguridad:"),
        "recognitions": ("Hoy se reconoció a {count} persona:", "Hoy se reconocieron {count} personas:"),
        "conversations": ("Hoy hay {count} conversación:", "Hoy hay {count} conversaciones:"),
        "location": ("Hoy hay {count} actualización de ubicación:", "Hoy hay {count} actualizaciones de ubicación:"),
        "objects": ("Hoy hay {count} objeto recordado:", "Hoy hay {count} objetos recordados:"),
        "help": ("Hoy hay {count} petición de ayuda:", "Hoy hay {count} peticiones de ayuda:"),
        "memory": ("Hoy hay {count} posible pérdida de memoria:", "Hoy hay {count} posibles pérdidas de memoria:"),
        "none": {
            "warnings": "Hoy no se ha registrado ningún aviso de seguridad.",
            "recognitions": "Hoy no se ha reconocido a nadie.",
            "conversations": "Hoy no hay conversaciones registradas.",
            "location": "Hoy no hay actualizaciones de ubicación.",
            "objects": "Hoy no se ha recordado ningún objeto.",
            "help": "Hoy no ha habido peticiones de ayuda.",
            "memory": "Hoy no se ha registrado ninguna pérdida de memoria.",
        },
        "line": "{time} — {summary}",
    },
    "gl": {
        "warnings": ("Hoxe hai {count} aviso de seguridade:", "Hoxe hai {count} avisos de seguridade:"),
        "recognitions": ("Hoxe recoñeceuse a {count} persoa:", "Hoxe recoñecéronse {count} persoas:"),
        "conversations": ("Hoxe hai {count} conversa:", "Hoxe hai {count} conversas:"),
        "location": ("Hoxe hai {count} actualización de localización:", "Hoxe hai {count} actualizacións de localización:"),
        "objects": ("Hoxe hai {count} obxecto recordado:", "Hoxe hai {count} obxectos recordados:"),
        "help": ("Hoxe hai {count} petición de axuda:", "Hoxe hai {count} peticións de axuda:"),
        "memory": ("Hoxe hai {count} posible perda de memoria:", "Hoxe hai {count} posibles perdas de memoria:"),
        "none": {
            "warnings": "Hoxe non se rexistrou ningún aviso de seguridade.",
            "recognitions": "Hoxe non se recoñeceu a ninguén.",
            "conversations": "Hoxe non hai conversas rexistradas.",
            "location": "Hoxe non hai actualizacións de localización.",
            "objects": "Hoxe non se recordou ningún obxecto.",
            "help": "Hoxe non houbo peticións de axuda.",
            "memory": "Hoxe non se rexistrou ningunha perda de memoria.",
        },
        "line": "{time} — {summary}",
    },
    "en": {
        "warnings": ("There is {count} safety warning today:", "There are {count} safety warnings today:"),
        "recognitions": ("{count} person was recognised today:", "{count} people were recognised today:"),
        "conversations": ("There is {count} conversation today:", "There are {count} conversations today:"),
        "location": ("There is {count} location update today:", "There are {count} location updates today:"),
        "objects": ("There is {count} remembered object today:", "There are {count} remembered objects today:"),
        "help": ("There is {count} help request today:", "There are {count} help requests today:"),
        "memory": ("There is {count} possible memory lapse today:", "There are {count} possible memory lapses today:"),
        "none": {
            "warnings": "No safety warnings have been registered today.",
            "recognitions": "No one has been recognised today.",
            "conversations": "There are no conversations registered today.",
            "location": "There are no location updates today.",
            "objects": "No objects have been remembered today.",
            "help": "There have been no help requests today.",
            "memory": "No memory lapses have been registered today.",
        },
        "line": "{time} — {summary}",
    },
}


def family_zone():
    zone_name = os.getenv("AURA_FAMILY_TIMEZONE", "Europe/Madrid")
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(zone_name)
    except Exception:
        return timezone.utc


def family_language(requested: Optional[str]) -> str:
    if requested in FAMILY_LANGUAGE_NAMES:
        return requested
    default = (os.getenv("AURA_FAMILY_LANGUAGE", FAMILY_LANGUAGE_FALLBACK) or "").lower()
    return default if default in FAMILY_LANGUAGE_NAMES else FAMILY_LANGUAGE_FALLBACK


SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setembro": 9, "octubre": 10,
    "noviembre": 11, "novembro": 11, "diciembre": 12, "decembro": 12,
}
MONTH_NAMES = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
    "gl": ["xaneiro", "febreiro", "marzo", "abril", "maio", "xuño", "xullo", "agosto", "setembro", "outubro", "novembro", "decembro"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
}


def family_target_date(question: str) -> date:
    """Resolve which local calendar day the question refers to (defaults to today)."""
    today = now().astimezone(family_zone()).date()
    normalized = normalize_memory_text(question)
    if any(word in normalized for word in ("anteayer", "antonte", "antes de onte")):
        return today - timedelta(days=2)
    if any(word in normalized for word in ("ayer", "onte", "yesterday")):
        return today - timedelta(days=1)
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", normalized)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            pass
    match = re.search(r"(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+(\d{4}))?", normalized)
    if match:
        month = SPANISH_MONTHS.get(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        if month:
            try:
                return date(year, month, int(match.group(1)))
            except ValueError:
                pass
    return today


def family_day_label(target: date, language: str) -> str:
    today = now().astimezone(family_zone()).date()
    current, previous = {"es": ("hoy", "ayer"), "gl": ("hoxe", "onte"), "en": ("today", "yesterday")}.get(
        language, ("hoy", "ayer")
    )
    if target == today:
        return current
    if target == today - timedelta(days=1):
        return previous
    months = MONTH_NAMES.get(language, MONTH_NAMES["es"])
    if language == "en":
        return f"on {months[target.month - 1]} {target.day}, {target.year}"
    prefix = "o" if language == "gl" else "el"
    return f"{prefix} {target.day} de {months[target.month - 1]} de {target.year}"


def localize_day(text: str, day_label: str, language: str) -> str:
    capitalized = day_label[:1].upper() + day_label[1:]
    if language == "gl":
        return text.replace("Hoxe ", capitalized + " ").replace("Hoxe", capitalized)
    if language == "en":
        return text.replace("today", day_label)
    return text.replace("Hoy ", capitalized + " ").replace("Hoy", capitalized)


def family_day_window(target: date) -> tuple[datetime, datetime]:
    """UTC window for the requested local calendar day (up to now when it is today)."""
    zone = family_zone()
    start_local = datetime(target.year, target.month, target.day, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    current = now().astimezone(zone)
    end = min(end_local, current) if target == current.date() else end_local
    return start_local.astimezone(timezone.utc), end.astimezone(timezone.utc)


FAMILY_PERIOD_WORDS: dict[str, tuple[tuple[str, int], ...]] = {
    "es": (("semana", 7), ("mes", 30), ("ultimos dias", 7), ("ultimamente", 7)),
    "gl": (("semana", 7), ("mes", 30), ("ultimos dias", 7), ("ultimamente", 7)),
    "en": (("week", 7), ("month", 30), ("last days", 7), ("lately", 7)),
}
FAMILY_PERIOD_LABELS: dict[str, dict[int, str]] = {
    "es": {7: "esta semana", 30: "este mes"},
    "gl": {7: "esta semana", 30: "este mes"},
    "en": {7: "this week", 30: "this month"},
}
FAMILY_PERIOD_PREVIOUS: dict[str, dict[int, str]] = {
    "es": {7: "la semana pasada", 30: "el mes pasado"},
    "gl": {7: "a semana pasada", 30: "o mes pasado"},
    "en": {7: "last week", 30: "last month"},
}


def family_period(question: str, language: str, target: date) -> Optional[tuple[datetime, datetime, str]]:
    """Ventana para 'esta semana' (lunes–domingo) o 'este mes' (por defecto, un solo día)."""
    normalized = normalize_memory_text(question)
    days = next(
        (value for word, value in FAMILY_PERIOD_WORDS.get(language, FAMILY_PERIOD_WORDS["es"]) if word in normalized),
        None,
    )
    if days is None:
        return None
    previous = any(word in normalized for word in ("pasada", "pasado", "anterior", "last"))
    labels = (FAMILY_PERIOD_PREVIOUS if previous else FAMILY_PERIOD_LABELS).get(language, FAMILY_PERIOD_LABELS["es"])
    if days == 7:
        anchor = target - timedelta(days=7) if previous else target
        monday = anchor - timedelta(days=anchor.weekday())
        start, _ = family_day_window(monday)
        _, end = family_day_window(monday + timedelta(days=6)) if previous else family_day_window(anchor)
        return start, end, labels[7]
    anchor = target - timedelta(days=days) if previous else target
    start, _ = family_day_window(anchor - timedelta(days=days - 1))
    _, end = family_day_window(anchor)
    return start, end, labels[30]


def family_time_label(moment: datetime) -> str:
    return moment.astimezone(family_zone()).strftime("%H:%M")


def family_intent(question: str) -> Optional[str]:
    normalized = normalize_memory_text(question)
    for intent, keywords in FAMILY_INTENT_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return intent
    return None


FAMILY_CLOSERS = {
    "no gracias", "nada mas", "muchas gracias", "gracias", "eso es todo", "hasta luego",
    "adios", "adios gracias", "ok gracias", "vale gracias", "perfecto gracias", "ninguna mas",
    "no nada mas", "nada mas gracias", "si gracias",
}
FAMILY_CLOSERS_REPLY = {
    "es": "De nada. Aquí estoy cuando me necesites.",
    "gl": "De nada. Aquí estou cando me necesites.",
    "en": "You're welcome. I'm here whenever you need me.",
}


def family_is_closing(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", normalize_memory_text(text))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in FAMILY_CLOSERS


def family_day_events(start: datetime, end: datetime) -> list[Event]:
    events = repository.list_events(500, None)
    relevant = [
        event for event in events
        if start <= event.occurred_at <= end
        and not (event.kind == "conversation" and is_transcription_artifact(event.summary))
    ]
    relevant.sort(key=lambda event: event.occurred_at)
    return relevant


def build_family_summary(events: list[Event], language: str, question: str = "", day_label: str = "hoy") -> str:
    labels = FAMILY_DAY_LABELS.get(language, FAMILY_DAY_LABELS[FAMILY_LANGUAGE_FALLBACK])
    focused_labels = FAMILY_FOCUSED_LABELS.get(language, FAMILY_FOCUSED_LABELS[FAMILY_LANGUAGE_FALLBACK])
    intent = family_intent(question)
    if intent:
        kinds = FAMILY_INTENTS[intent]
        focused = [event for event in events if event.kind in kinds]
        if not focused:
            return localize_day(focused_labels["none"][intent], day_label, language)
        header = localize_day(
            focused_labels[intent][0] if len(focused) == 1 else focused_labels[intent][1], day_label, language
        )
        lines = [
            focused_labels["line"].format(time=family_time_label(event.occurred_at), summary=event.summary)
            for event in focused[:12]
        ]
        return header.format(count=len(focused)) + " " + "; ".join(lines)
    if not events:
        return localize_day(labels["empty"], day_label, language)
    counts = Counter(event.kind for event in events)
    parts = [localize_day(labels["header"], day_label, language).format(total=len(events))]
    details = []
    for kind, count in counts.items():
        forms = labels["kinds"].get(kind)
        if not forms:
            continue
        template = forms[0] if count == 1 else forms[1]
        details.append(template.format(count=count))
    if details:
        parts.append(labels["join"].join(details) + ".")
    names: list[str] = []
    for event in events:
        if event.kind != "recognition":
            continue
        name = event.metadata.get("person_name") or event.metadata.get("display_name")
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name)
    if names:
        joined = labels["and"].join(names) if len(names) > 1 else names[0]
        parts.append(labels["recognized"].format(names=joined))
    urgent = sum(1 for event in events if event.severity in {"attention", "urgent"})
    if urgent:
        parts.append(labels["urgent"].format(count=urgent))
    parts.append(labels["closing"])
    return " ".join(parts)


OBJECT_LOOKUP_LABELS = {
    "es": {
        "found": "Se vio {object} por última vez en {place} ({moment}).",
        "found_no_place": "Se vio {object} por última vez {moment}.",
    },
    "gl": {
        "found": "Viu {object} por última vez en {place} ({moment}).",
        "found_no_place": "Viu {object} por última vez {moment}.",
    },
    "en": {
        "found": "{object} was last seen in {place} ({moment}).",
        "found_no_place": "{object} was last seen {moment}.",
    },
}


def object_lookup_answer(question: str, language: str) -> Optional[str]:
    """Respuesta determinista para «¿dónde está X?» cuando la IA no esta disponible."""
    matches = find_object_memories(question, limit=1)
    if not matches:
        return None
    memory = matches[0]
    labels = OBJECT_LOOKUP_LABELS.get(language, OBJECT_LOOKUP_LABELS["es"])
    moment = memory.seen_at.astimezone(family_zone()).strftime("%d/%m/%Y %H:%M")
    object_label = memory.object_name.strip().lower()
    if memory.place:
        return labels["found"].format(object=object_label, place=memory.place, moment=moment)
    return labels["found_no_place"].format(object=object_label, moment=moment)


FAMILY_ALERT_TOOL = {
    "type": "function",
    "name": "registrar_aviso",
    "description": (
        "Registra un aviso automático por WhatsApp a la red de cuidados cuando el paciente "
        "manifieste algo concreto (por ejemplo dolor, empeoramiento, caída). Úsala SOLO cuando "
        "el familiar pida explícitamente que se le avise ante algo, o confirme con un 'sí' una "
        "propuesta tuya de avisar. Solo define palabras clave que disparan un aviso cuando el "
        "paciente las dice; NO sirve para programar informes, horarios ni tareas recurrentes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "descripcion": {"type": "string", "description": "Qué se debe avisar, en una frase breve."},
            "palabras_clave": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Palabras que, si aparecen en una frase del paciente, disparan el aviso (p. ej. 'empeora', 'dolor').",
            },
        },
        "required": ["descripcion", "palabras_clave"],
    },
}


FAMILY_CALENDAR_TOOL = {
    "type": "function",
    "name": "crear_recordatorio",
    "description": (
        "Crea un recordatorio en la agenda de Faro, para el paciente o para la familia. Úsala "
        "cuando el familiar pida programar o recordar algo (una pastilla, una cita, una rutina). "
        "Indica el título y la fecha y hora de inicio en ISO 8601; si el familiar no da la hora, "
        "pídesela antes de crear el recordatorio."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "titulo": {"type": "string", "description": "Qué hay que recordar, en una frase breve."},
            "fecha_hora": {"type": "string", "description": "Inicio en ISO 8601, p. ej. 2026-09-20T18:30:00+02:00."},
            "categoria": {
                "type": "string",
                "enum": ["medication", "routine", "appointment", "other"],
                "description": "Tipo de recordatorio.",
            },
            "avisar_minutos_antes": {"type": "integer", "description": "Minutos de antelación del aviso (0-1440)."},
            "para_paciente": {"type": "boolean", "description": "true si es para el paciente; false si es para la familia."},
            "recurrencia": {
                "type": "string",
                "enum": ["ninguna", "diaria", "semanal", "mensual"],
                "description": "Si se repite: una vez (ninguna), diaria, semanal o mensual.",
            },
            "repetir_cada": {"type": "integer", "description": "Cada cuántos días/semanas/meses se repite (por defecto 1)."},
            "repetir_hasta": {"type": "string", "description": "Fecha final de la repetición en formato ISO (YYYY-MM-DD); opcional."},
            "dias_semana": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Solo si la repetición es semanal: días 0=lunes, 1=martes, …, 6=domingo.",
            },
            "notas": {"type": "string", "description": "Detalle opcional."},
        },
        "required": ["titulo", "fecha_hora"],
    },
}

CALENDAR_CATEGORIES = {"medication", "routine", "appointment", "other"}


def execute_family_tool(name: str, arguments: str) -> dict:
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {"status": "error", "detail": "invalid arguments"}
    if name == "registrar_aviso":
        keywords = args.get("palabras_clave") or []
        description = args.get("descripcion") or ""
        if not isinstance(keywords, list) or not description:
            return {"status": "error", "detail": "missing description or keywords"}
        rule = repository.add_family_alert_rule([str(keyword) for keyword in keywords], str(description))
        return {"status": "ok", "rule_id": rule["id"], "description": rule["description"], "keywords": rule["keywords"]}
    if name == "crear_recordatorio":
        title = str(args.get("titulo") or "").strip()
        raw_start = args.get("fecha_hora")
        if not title or not raw_start:
            return {"status": "error", "detail": "missing title or start date"}
        try:
            start_at = datetime.fromisoformat(str(raw_start))
        except ValueError:
            return {"status": "error", "detail": "invalid start date"}
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=family_zone())
        category = str(args.get("categoria") or "other")
        if category not in CALENDAR_CATEGORIES:
            category = "other"
        try:
            reminder = int(args.get("avisar_minutos_antes", 15))
        except (TypeError, ValueError):
            reminder = 15
        notes = args.get("notas")
        recurrence_map = {"ninguna": "none", "diaria": "daily", "semanal": "weekly", "mensual": "monthly"}
        recurrence = recurrence_map.get(str(args.get("recurrencia") or "ninguna"), "none")
        try:
            interval = int(args.get("repetir_cada", 1))
        except (TypeError, ValueError):
            interval = 1
        recurrence_until = None
        if args.get("repetir_hasta"):
            try:
                recurrence_until = date.fromisoformat(str(args["repetir_hasta"])[:10])
            except ValueError:
                recurrence_until = None
        weekdays = args.get("dias_semana")
        recurrence_weekdays = None
        if recurrence == "weekly" and isinstance(weekdays, list):
            recurrence_weekdays = sorted({
                int(day) for day in weekdays
                if isinstance(day, (int, float)) and 0 <= int(day) <= 6
            })
        event = CalendarEvent(
            id=uuid4(), created_at=now(), title=title, category=category, start_at=start_at,
            duration_minutes=30, reminder_minutes_before=max(0, min(1440, reminder)),
            notes=(str(notes).strip() or None) if notes else None,
            for_patient=bool(args.get("para_paciente", True)), enabled=True,
            recurrence=recurrence, recurrence_interval=max(1, min(366, interval)),
            recurrence_until=recurrence_until, recurrence_weekdays=recurrence_weekdays,
        )
        repository.calendar_events[event.id] = event
        repository.save_calendar_events()
        return {
            "status": "ok", "event_id": str(event.id), "title": event.title,
            "start_at": event.start_at.isoformat(), "category": event.category,
            "for_patient": event.for_patient,
        }
    return {"status": "error", "detail": "unknown tool"}


def openai_family_answer(
    question: str, events: list[Event], language: str, day_label: str = "hoy",
    history: Optional[list[dict[str, str]]] = None,
) -> Optional[str]:
    api_key = os.getenv("AURA_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    profile = repository.get_patient_profile()
    patient_name = profile.preferred_name if profile and profile.preferred_name else "el paciente"
    lines: list[str] = []
    for event in events:
        speaker = event.metadata.get("speaker")
        speaker_label = f" [{speaker}]" if speaker else ""
        moment = event.occurred_at.astimezone(family_zone()).strftime("%H:%M")
        lines.append(f"- {moment} · {event.kind}{speaker_label}: {event.summary}")
    context = "\n".join(lines) if lines else "(sin eventos registrados en ese día)"
    object_lines: list[str] = []
    for memory in sorted(repository.object_memories.values(), key=lambda item: item.seen_at, reverse=True)[:8]:
        moment = memory.seen_at.astimezone(family_zone()).strftime("%d/%m %H:%M")
        where = f" en {memory.place}" if memory.place else ""
        object_lines.append(f"- {memory.object_name}{where} ({moment})")
    if object_lines:
        context += "\n\nObjetos recordados recientemente:\n" + "\n".join(object_lines)
    agenda_items: list[str] = []
    reference = now()
    for calendar_event in sorted(repository.calendar_events.values(), key=lambda item: item.start_at):
        if not calendar_event.enabled or calendar_event.start_at < reference - timedelta(days=1):
            continue
        momento = calendar_event.start_at.astimezone(family_zone()).strftime("%d/%m %H:%M")
        destino = "paciente" if calendar_event.for_patient else "familia"
        agenda_items.append(f"- {momento} · {calendar_event.title} ({calendar_event.category}, {destino})")
    if agenda_items:
        context += "\n\nAgenda próxima:\n" + "\n".join(agenda_items[:15])
    transcript = "\n".join(
        f"{'Familiar' if turn.get('role') == 'user' else 'Faro'}: {turn.get('content', '')}"
        for turn in (history or [])
    )
    today = now().astimezone(family_zone()).strftime("%d/%m/%Y")
    contacts = [contact.display_name for contact in enabled_alert_contacts()]
    contacts_label = ", ".join(contacts) if contacts else "sin contactos configurados todavía"
    instructions = (
        f"Eres Faro, el asistente conversacional de Faro da Memoria para familiares y cuidadores "
        f"de {patient_name}. Hoy es {today}. Responde SIEMPRE en "
        f"{FAMILY_LANGUAGE_NAMES.get(language, 'español')}, con tono cercano, claro y breve "
        "(máximo 5 frases).\n\n"
        "Tu ámbito es EXCLUSIVAMENTE el cuidado de "
        f"{patient_name} a través de Faro: su día, sus eventos, los avisos y la red de cuidados. "
        "Puedes ser cercano y natural, pero NO debes realizar tareas ajenas a ese ámbito (chistes, "
        "conocimiento general, redacciones, traducciones, cálculos, etc.); si te lo piden, declina "
        "con amabilidad y ofrece ayuda sobre el paciente.\n\n"
        "Tus capacidades reales son:\n"
        "1) Consultar y explicar el registro de eventos del paciente (abajo tienes los eventos "
        f"del día consultado: {day_label}).\n"
        f"2) Registrar avisos automáticos por WhatsApp a la red de cuidados ({contacts_label}) "
        "ante palabras clave concretas, usando la herramienta registrar_aviso.\n"
        "3) Programar recordatorios en la agenda de Faro (del paciente o de la familia) con la "
        "herramienta crear_recordatorio, usando la fecha y hora que indique el familiar.\n\n"
        "Reglas que debes cumplir siempre:\n"
        "- No repitas el resumen del día salvo que te pregunten por el día o por los eventos. Si "
        "el mensaje es un saludo, una despedida, un agradecimiento o charla, responde con "
        "naturalidad y brevedad SIN enumerar eventos ni repetir resúmenes anteriores.\n"
        "- Si el familiar se despide, agradece o da por terminada la conversación, responde "
        "brevemente y añade la etiqueta [FIN] al final (y solo en ese caso).\n"
        "- No inventes funciones: NO existen informes periódicos o diarios, resúmenes programados "
        "ni envíos a demanda. Si te lo piden, dilo con naturalidad y ofrece solo lo que sí puedes "
        "hacer.\n"
        "- Para crear un recordatorio necesitas TODOS estos campos: título, fecha y hora, categoría "
        "(medicación/rutina/cita/otra), con cuántos minutos de antelación avisar, si es para el "
        "paciente o para la familia y si se repite (una vez, diaria, semanal —indicando los días— o "
        "mensual, «cada N» y hasta qué fecha). Si falta alguno, pregúntalo (de uno en uno, sin "
        "interrogar); si no te dan la antelación, propón 15 minutos y confírmalo. Cuando tengas "
        "todo, llama a crear_recordatorio y resume los datos para confirmar.\n"
        "- Si preguntan por la agenda o los próximos recordatorios, responde con «Agenda próxima»; "
        "si no aparece nada, dilo con claridad.\n"
        "- No inventes datos del paciente: usa solo los eventos y datos proporcionados; si algo no "
        "aparece, dilo con claridad.\n"
        "- Si preguntan por un objeto (llaves, mando, gafas...), usa «Objetos recordados "
        "recientemente» y responde con el lugar y el momento en que se vio por última vez; si no "
        "aparece, dilo con claridad.\n"
        "- No des consejos médicos ni alarmes sin motivo.\n"
        "- Sé coherente con los mensajes anteriores de esta conversación y no te repitas.\n"
        "- Si el familiar pide que se le avise ante algo concreto (o confirma con un 'sí' una "
        "propuesta tuya de avisar), llama a la herramienta registrar_aviso con una descripción "
        "breve y las palabras clave, y confírmale que el aviso queda activo por WhatsApp.\n\n"
        "Registro de eventos del paciente:\n"
        f"{context}"
    )
    user_text = f"Mensaje del familiar: {question}"
    if transcript:
        user_text = f"Conversación previa:\n{transcript}\n\n{user_text}"
    input_items: list[dict] = [{"role": "user", "content": [{"type": "input_text", "text": user_text}]}]
    text_answer: Optional[str] = None
    for _ in range(3):
        payload = json.dumps({
            "model": os.getenv("AURA_OPENAI_MODEL", "gpt-4.1-mini"),
            "instructions": instructions,
            "input": input_items,
            "tools": [FAMILY_ALERT_TOOL, FAMILY_CALENDAR_TOOL],
            "temperature": 0.2,
            "max_output_tokens": 500,
        }).encode("utf-8")
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read())
        function_calls = []
        for item in body.get("output", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                function_calls.append(item)
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        text_answer = text.strip()
        if not function_calls:
            return text_answer
        for call in function_calls:
            result = execute_family_tool(str(call.get("name", "")), str(call.get("arguments", "{}")))
            input_items.append({
                "type": "function_call", "name": call.get("name"),
                "arguments": call.get("arguments"), "call_id": call.get("call_id"),
            })
            input_items.append({
                "type": "function_call_output", "call_id": call.get("call_id"),
                "output": json.dumps(result, ensure_ascii=False),
            })
    return text_answer


@app.post("/v1/family/ask", response_model=FamilyAnswer)
def ask_family_question(
    request: FamilyQuestion, authorization: Optional[str] = Header(default=None),
) -> FamilyAnswer:
    require_auth(authorization)
    question = request.question.strip()
    if len(question) < 2:
        raise HTTPException(status_code=422, detail="Question is too short")
    conversation_id = request.conversation_id or uuid4().hex
    history = repository.family_messages(conversation_id, limit=10)
    repository.add_family_message(conversation_id, "user", question)
    language = family_language(request.language)
    target = family_target_date(question)
    period = family_period(question, language, target)
    if period is not None:
        start, end, day_label = period
    else:
        day_label = family_day_label(target, language)
        start, end = family_day_window(target)
    if family_is_closing(question):
        answer = FAMILY_CLOSERS_REPLY.get(language, FAMILY_CLOSERS_REPLY["es"])
        repository.add_family_message(conversation_id, "assistant", answer)
        return FamilyAnswer(
            answer=answer, language=language, generated_by="summary",
            window_start=start, window_end=end, conversation_id=conversation_id,
            end_conversation=True, sources=[],
        )
    events = family_day_events(start, end)
    generated_by = "summary"
    answer: Optional[str] = None
    try:
        answer = openai_family_answer(question, events, language, day_label, history)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        answer = None
    end_conversation = False
    if answer:
        if "[FIN]" in answer:
            answer = answer.replace("[FIN]", "").strip()
            end_conversation = True
        if not answer:
            answer = FAMILY_CLOSERS_REPLY.get(language, FAMILY_CLOSERS_REPLY["es"])
        generated_by = "openai"
    else:
        answer = object_lookup_answer(question, language) or build_family_summary(events, language, question, day_label)
    repository.add_family_message(conversation_id, "assistant", answer)
    sources = [
        FamilyAnswerSource(
            event_id=event.id,
            kind=event.kind,
            summary=event.summary,
            occurred_at=event.occurred_at,
            speaker=(str(event.metadata["speaker"]) if event.metadata.get("speaker") else None),
        )
        for event in events[-10:]
    ]
    return FamilyAnswer(
        answer=answer, language=language, generated_by=generated_by,
        window_start=start, window_end=end, conversation_id=conversation_id,
        end_conversation=end_conversation, sources=sources,
    )


@app.post("/v1/pairing-invites", response_model=PairingInvite, status_code=201)
def create_pairing_invite(request: PairingInviteCreate, authorization: Optional[str] = Header(default=None)) -> PairingInvite:
    actor = require_auth(authorization)
    code = secrets.token_hex(4).upper()
    invite = PairingInvite(code=code, role=request.role, expires_at=now() + timedelta(minutes=10))
    with repository.lock:
        repository.event_db.execute(
            "INSERT INTO pairing_invites(code_hash, role, care_circle_id, expires_at) VALUES (?, ?, ?, ?)",
            (credential_hash(code), invite.role, actor, invite.expires_at.isoformat()),
        )
        repository.event_db.commit()
    return invite


@app.post("/v1/pairing/claim", response_model=PairingResult)
def claim_pairing(request: PairingClaim) -> PairingResult:
    code_hash = credential_hash(request.code.upper())
    claimed_at = now()
    with repository.lock:
        invite = repository.event_db.execute(
            "SELECT role, care_circle_id, expires_at FROM pairing_invites "
            "WHERE code_hash=? AND consumed_at IS NULL", (code_hash,),
        ).fetchone()
        if invite is None or datetime.fromisoformat(invite["expires_at"]) < claimed_at:
            raise HTTPException(status_code=404, detail="Pairing code is invalid or expired")
        consumed = repository.event_db.execute(
            "UPDATE pairing_invites SET consumed_at=? WHERE code_hash=? AND consumed_at IS NULL",
            (claimed_at.isoformat(), code_hash),
        )
        if consumed.rowcount != 1:
            repository.event_db.rollback()
            raise HTTPException(status_code=404, detail="Pairing code is invalid or expired")
        device_credential = secrets.token_urlsafe(32)
        repository.event_db.execute(
            "INSERT INTO device_credentials(id, token_hash, care_circle_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), credential_hash(device_credential), invite["care_circle_id"], invite["role"], claimed_at.isoformat()),
        )
        repository.event_db.commit()
    return PairingResult(
        care_circle_id=invite["care_circle_id"], role=invite["role"], linked=True,
        device_credential=device_credential,
    )


@app.post("/v1/device-credentials/validate", response_model=DeviceCredentialStatus)
def validate_device_credential(authorization: Optional[str] = Header(default=None)) -> DeviceCredentialStatus:
    token_hash = credential_hash(extract_bearer(authorization))
    credential = repository.event_db.execute(
        "SELECT care_circle_id, role FROM device_credentials WHERE token_hash=? AND revoked_at IS NULL",
        (token_hash,),
    ).fetchone()
    if credential is None:
        raise HTTPException(status_code=401, detail="Invalid device credential")
    return DeviceCredentialStatus(
        active=True, care_circle_id=credential["care_circle_id"], role=credential["role"],
    )


@app.post("/v1/people", response_model=Person, status_code=201)
def create_person(request: PersonCreate, authorization: Optional[str] = Header(default=None)) -> Person:
    require_auth(authorization)
    if not request.consent_granted:
        raise HTTPException(status_code=422, detail="Explicit consent is required before enrollment")
    person = Person(id=uuid4(), created_at=now(), **request.model_dump())
    with repository.lock:
        repository.people[person.id] = person
        repository.save_people()
    return person


@app.get("/v1/people", response_model=list[Person])
def list_people(authorization: Optional[str] = Header(default=None)) -> list[Person]:
    require_auth(authorization)
    return sorted(repository.people.values(), key=lambda item: item.display_name.lower())


@app.get("/v1/people/{person_id}", response_model=Person)
def get_person(person_id: UUID, authorization: Optional[str] = Header(default=None)) -> Person:
    require_auth(authorization)
    return person_or_404(person_id)


@app.patch("/v1/people/{person_id}", response_model=Person)
def update_person(
    person_id: UUID,
    request: PersonUpdate,
    authorization: Optional[str] = Header(default=None),
) -> Person:
    require_auth(authorization)
    person = person_or_404(person_id)
    changes = request.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one field must be updated")
    updated = person.model_copy(update=changes)
    with repository.lock:
        repository.people[person_id] = updated
        repository.save_people()
    return updated


@app.get("/v1/people/{person_id}/profile-photo", response_class=Response)
def get_person_profile_photo(
    person_id: UUID,
    authorization: Optional[str] = Header(default=None),
) -> Response:
    require_auth(authorization)
    person_or_404(person_id)
    photo = repository.person_photo(person_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Profile photo is unavailable")
    image, media_type = photo
    return Response(content=image, media_type=media_type, headers={"Cache-Control": "no-store, private"})


@app.get("/v1/people/{person_id}/face-samples/{sample_index}", response_class=Response)
def get_person_face_sample(
    person_id: UUID,
    sample_index: int,
    authorization: Optional[str] = Header(default=None),
) -> Response:
    require_auth(authorization)
    person_or_404(person_id)
    photo = repository.person_photo_sample(person_id, sample_index)
    if photo is None:
        raise HTTPException(status_code=404, detail="Face sample is unavailable")
    image, media_type = photo
    return Response(content=image, media_type=media_type, headers={"Cache-Control": "no-store, private"})


@app.post("/v1/people/{person_id}/face-samples", response_model=Person)
def enroll_face_samples(person_id: UUID, files: Annotated[list[UploadFile], File()], authorization: Optional[str] = Header(default=None)) -> Person:
    require_auth(authorization)
    person = person_or_404(person_id)
    images = read_face_images(files)
    face_provider.delete(person_id)
    indexed = face_provider.enroll(person_id, images)
    if indexed < 1:
        face_provider.delete(person_id)
        raise HTTPException(status_code=422, detail="Each image must contain one usable face")
    photos_saved = repository.save_person_photos(person_id, images)
    updated = person.model_copy(update={
        "enrollment_samples": indexed,
        "enrollment_complete": True,
        "profile_photo_available": photos_saved > 0,
    })
    repository.people[person_id] = updated
    repository.save_people()
    return updated


@app.delete("/v1/people/{person_id}", status_code=204, response_class=Response)
def delete_person(person_id: UUID, authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    person_or_404(person_id)
    face_provider.delete(person_id)
    repository.delete_person_photo(person_id)
    with repository.lock:
        repository.people.pop(person_id, None)
        repository.memories = {key: value for key, value in repository.memories.items() if value.person_id != person_id}
        repository.save_people()
    linked_contacts = [contact for contact in repository.care_contacts.values() if contact.known_person_id == person_id]
    for contact in linked_contacts:
        repository.care_contacts[contact.id] = contact.model_copy(update={"known_person_id": None})
    if linked_contacts:
        repository.save_care_contacts()
    return Response(status_code=204)


@app.post("/v1/recognitions", response_model=RecognitionResult)
def recognize(request: Request, files: Annotated[list[UploadFile], File()], authorization: Optional[str] = Header(default=None)) -> RecognitionResult:
    actor = require_auth(authorization)
    record_usage(actor)
    images = read_images(files, required=3)
    candidates: list[FaceCandidate] = []
    frames_with_faces = 0
    for image in images:
        try:
            candidates.extend(face_provider.search(image))
            frames_with_faces += 1
        except NoFaceDetectedError:
            continue
    if frames_with_faces < CONSENSUS_MINIMUM:
        return RecognitionResult(status="unknown", reason="No clear face detected across enough frames")
    person_id, confidence, reason = decide(candidates)
    if person_id == PATIENT_FACE_ID:
        profile = repository.get_patient_profile()
        if profile is not None and profile.face_enrollment_complete:
            patient = Person(
                id=PATIENT_FACE_ID, display_name=profile.preferred_name, relationship="eres tú",
                consent_granted=True, created_at=now(), enrollment_samples=profile.face_enrollment_samples,
                enrollment_complete=True, profile_photo_available=profile.profile_photo_available,
            )
            return RecognitionResult(status="confirmed", person=patient, confidence=confidence, reason=reason, is_patient=True)
    if person_id is not None and person_id in repository.people:
        key = f"{actor}:person:{person_id}"
        if repository.last_outcome.get(key, datetime.min.replace(tzinfo=timezone.utc)) > now() - SAME_PERSON_COOLDOWN:
            return RecognitionResult(status="unknown", reason="Repeated announcement suppressed")
        repository.last_outcome[key] = now()
        return RecognitionResult(status="confirmed", person=repository.people[person_id], confidence=confidence, reason=reason)
    patient_frames = sum(1 for candidate in candidates if candidate.person_id == PATIENT_FACE_ID and candidate.confidence >= CONFIDENCE_MINIMUM)
    if patient_frames >= CONSENSUS_MINIMUM:
        return RecognitionResult(status="unknown", confidence=confidence, reason="Possible patient self-image; review suppressed")
    known_frames = [candidate for candidate in candidates if candidate.person_id in repository.people]
    if known_frames:
        return RecognitionResult(status="unknown", confidence=confidence, reason="Likely known person below consensus; review suppressed")
    review_key = f"{actor}:review"
    if repository.last_review_created.get(review_key, datetime.min.replace(tzinfo=timezone.utc)) > now() - REVIEW_COOLDOWN:
        return RecognitionResult(status="unknown", confidence=confidence, reason="Recent pending review; duplicate suppressed")
    repository.last_review_created[review_key] = now()
    review = ReviewItem(id=uuid4(), created_at=now(), status="pending", candidate_person_ids=[], confidences=[candidate.confidence for candidate in candidates])
    repository.save_review(review)
    repository.save_review_image(review.id, images[0])
    return RecognitionResult(status="review_required", review_id=review.id, reason=reason)


@app.get("/v1/reviews", response_model=list[ReviewItem])
def list_reviews(authorization: Optional[str] = Header(default=None)) -> list[ReviewItem]:
    require_auth(authorization)
    repository.purge_expired_reviews()
    return sorted(repository.reviews.values(), key=lambda item: item.created_at, reverse=True)


@app.get("/v1/reviews/{review_id}/image", response_class=Response)
def review_image(review_id: UUID, authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    review = repository.reviews.get(review_id)
    if review is None or review.status != "pending" or review.created_at < now() - REVIEW_IMAGE_TTL:
        repository.delete_review_evidence(review_id)
        raise HTTPException(status_code=404, detail="Review image is unavailable or expired")
    image = repository.load_review_image(review_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Review image is unavailable or expired")
    return Response(content=image, media_type="image/jpeg", headers={"Cache-Control": "no-store, private"})


@app.post("/v1/reviews/{review_id}/resolve", response_model=ReviewItem)
def resolve_review(review_id: UUID, resolution: ReviewResolution, authorization: Optional[str] = Header(default=None)) -> ReviewItem:
    require_auth(authorization)
    review = repository.reviews.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if resolution.person_id is not None:
        person = person_or_404(resolution.person_id)
        evidence = repository.load_review_image(review_id)
        if evidence and person.consent_granted:
            try:
                face_provider.enroll(resolution.person_id, [evidence])
            except Exception:
                pass
    updated = review.model_copy(update={"status": "resolved", "resolved_person_id": resolution.person_id})
    repository.save_review(updated)
    repository.delete_review_evidence(review_id)
    return updated


def find_object_memories(name: str, limit: int = 10) -> list[ObjectMemory]:
    """Objetos vistos cuyo nombre coincide con la consulta, del mas reciente al mas antiguo."""
    matches = [
        memory for memory in repository.object_memories.values()
        if object_memory_matches(memory, name)
    ]
    matches.sort(key=lambda memory: (memory.seen_at, memory.created_at), reverse=True)
    return matches[: max(1, limit)]


OBJECT_EVENT_SOURCES = {"glasses": "glasses", "phone": "phone", "portal": "portal", "backend": "backend"}


def record_object_event(memory: ObjectMemory) -> None:
    """Deja el avistamiento en la linea de tiempo del portal."""
    where = f" en {memory.place}" if memory.place else ""
    source = OBJECT_EVENT_SOURCES.get((memory.source or "glasses").strip().lower(), "glasses")
    repository.add_event(EventCreate(
        kind="object_location",
        summary=f"Se vio {memory.object_name}{where}",
        source=source,
        metadata={"object": memory.object_name, "location": memory.place or "", "confidence": memory.confidence or 0.0},
    ))


@app.post("/v1/object-memories", response_model=ObjectMemory, status_code=201)
def create_object_memory(
    request: ObjectMemoryCreate, authorization: Optional[str] = Header(default=None),
) -> ObjectMemory:
    require_auth(authorization)
    created_at = now()
    memory = ObjectMemory(
        id=uuid4(), object_name=request.object_name, place=request.place,
        description=request.description, confidence=request.confidence, source=request.source,
        seen_at=request.seen_at or created_at, created_at=created_at,
    )
    repository.object_memories[memory.id] = memory
    repository.save_object_memories()
    record_object_event(memory)
    return memory


@app.get("/v1/object-memories", response_model=list[ObjectMemory])
def list_object_memories(
    name: Optional[str] = None, limit: int = 20, authorization: Optional[str] = Header(default=None),
) -> list[ObjectMemory]:
    require_auth(authorization)
    if name:
        return find_object_memories(name, limit=min(limit, 50))
    memories = sorted(
        repository.object_memories.values(),
        key=lambda memory: (memory.seen_at, memory.created_at), reverse=True,
    )
    return memories[: min(limit, 50)]


@app.get("/v1/object-memories/last", response_model=Optional[ObjectMemory])
def last_object_memory(name: str, authorization: Optional[str] = Header(default=None)) -> Optional[ObjectMemory]:
    require_auth(authorization)
    matches = find_object_memories(name, limit=1)
    return matches[0] if matches else None


MEDICATION_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MEDICATION_GRACE = timedelta(minutes=20)


def parse_medication_time(value: str) -> tuple[int, int]:
    text = value.strip()
    if not MEDICATION_TIME_PATTERN.match(text):
        raise HTTPException(status_code=422, detail=f"Horario inválido: {value!r} (usa HH:MM)")
    hour, minute = text.split(":")
    return int(hour), int(minute)


def medication_schedule(plan: MedicationPlan, day: date) -> list[datetime]:
    return [
        datetime.combine(day, time(hour, minute), tzinfo=family_zone())
        for hour, minute in (parse_medication_time(item) for item in plan.times)
    ]


def medication_reference(moment: Optional[datetime]) -> datetime:
    if moment is None:
        return now()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=family_zone())
    return moment


def medication_reminder_message(plan: MedicationPlan) -> str:
    dose = f" ({plan.dose})" if plan.dose else ""
    return f"É a hora da túa medicación: {plan.medication}{dose}."


def run_medication_tick(moment: Optional[datetime] = None) -> MedicationTickResult:
    reference = medication_reference(moment)
    day = reference.astimezone(family_zone()).date()
    zone = family_zone()
    reminders: list[MedicationReminder] = []
    escalations: list[MedicationEscalation] = []
    for plan in repository.medication_plans.values():
        if not plan.enabled:
            continue
        for scheduled_at in medication_schedule(plan, day):
            existing = next(
                (
                    dose for dose in repository.medication_doses.values()
                    if dose.plan_id == plan.id and dose.scheduled_at == scheduled_at
                ),
                None,
            )
            if existing is not None or scheduled_at > reference:
                continue
            dose = MedicationDose(
                id=uuid4(), plan_id=plan.id, medication=plan.medication, dose=plan.dose,
                scheduled_at=scheduled_at, status="pending", created_at=now(),
            )
            repository.medication_doses[dose.id] = dose
            reminders.append(MedicationReminder(
                dose_id=dose.id, medication=plan.medication, dose=plan.dose,
                scheduled_at=scheduled_at, message=medication_reminder_message(plan),
            ))
            repository.add_event(EventCreate(
                kind="routine", source="backend", severity="info",
                summary=(
                    f"Recordatorio de medicación: {plan.medication} a las "
                    f"{scheduled_at.astimezone(zone).strftime('%H:%M')}"
                ),
                metadata={"dose_id": str(dose.id), "plan_id": str(plan.id), "status": "pending"},
            ))
    for dose in list(repository.medication_doses.values()):
        if dose.status != "pending" or reference - dose.scheduled_at < MEDICATION_GRACE:
            continue
        message = (
            "No se ha confirmado la medicación de las "
            f"{dose.scheduled_at.astimezone(zone).strftime('%H:%M')} ({dose.medication})."
        )
        contacts = enabled_alert_contacts()
        if contacts:
            deliveries, _ = send_alert_to_contacts(contacts, EmergencyAlertCreate(
                kind="medication", spoken_message=message, explicit_help_request=False,
            ))
            family_alert_status = (
                "sent" if any(delivery.message_id for _, delivery in deliveries)
                else "test_mode" if deliveries else "failed"
            )
        else:
            family_alert_status = "no_contact"
        repository.medication_doses[dose.id] = dose.model_copy(
            update={"status": "escalated", "escalated_at": reference}
        )
        escalations.append(MedicationEscalation(
            dose_id=dose.id, medication=dose.medication, scheduled_at=dose.scheduled_at,
            message=message, family_alert_status=family_alert_status,
        ))
        repository.add_event(EventCreate(
            kind="hazard", source="backend", severity="attention", summary=message,
            metadata={"dose_id": str(dose.id), "hazard": "medication",
                      "family_alert_status": family_alert_status},
        ))
    repository.save_medication_doses()
    return MedicationTickResult(at=reference, reminders=reminders, escalations=escalations)


@app.post("/v1/medication-plans", response_model=MedicationPlan, status_code=201)
def create_medication_plan(
    request: MedicationPlanCreate, authorization: Optional[str] = Header(default=None),
) -> MedicationPlan:
    require_auth(authorization)
    for item in request.times:
        parse_medication_time(item)
    plan = MedicationPlan(id=uuid4(), created_at=now(), **request.model_dump())
    repository.medication_plans[plan.id] = plan
    repository.save_medication_plans()
    return plan


@app.get("/v1/medication-plans", response_model=list[MedicationPlan])
def list_medication_plans(authorization: Optional[str] = Header(default=None)) -> list[MedicationPlan]:
    require_auth(authorization)
    return sorted(repository.medication_plans.values(), key=lambda plan: plan.created_at)


@app.patch("/v1/medication-plans/{plan_id}", response_model=MedicationPlan)
def update_medication_plan(
    plan_id: UUID, request: MedicationPlanUpdate, authorization: Optional[str] = Header(default=None),
) -> MedicationPlan:
    require_auth(authorization)
    plan = repository.medication_plans.get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Medication plan not found")
    changes = request.model_dump(exclude_unset=True)
    if "times" in changes:
        for item in changes["times"]:
            parse_medication_time(item)
    updated = plan.model_copy(update=changes)
    repository.medication_plans[plan_id] = updated
    repository.save_medication_plans()
    return updated


@app.delete("/v1/medication-plans/{plan_id}", status_code=204, response_class=Response)
def delete_medication_plan(plan_id: UUID, authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    repository.medication_plans.pop(plan_id, None)
    repository.save_medication_plans()
    return Response(status_code=204)


@app.get("/v1/medication-doses", response_model=list[MedicationDose])
def list_medication_doses(
    day: Optional[str] = None, authorization: Optional[str] = Header(default=None),
) -> list[MedicationDose]:
    require_auth(authorization)
    zone = family_zone()
    if day:
        try:
            target = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError as error:
            raise HTTPException(status_code=422, detail="La fecha debe ser YYYY-MM-DD") from error
    else:
        target = now().astimezone(zone).date()
    return sorted(
        [
            dose for dose in repository.medication_doses.values()
            if dose.scheduled_at.astimezone(zone).date() == target
        ],
        key=lambda dose: dose.scheduled_at,
    )


@app.post("/v1/medication-doses/{dose_id}/confirm", response_model=MedicationDose)
def confirm_medication_dose(dose_id: UUID, authorization: Optional[str] = Header(default=None)) -> MedicationDose:
    require_auth(authorization)
    dose = repository.medication_doses.get(dose_id)
    if dose is None:
        raise HTTPException(status_code=404, detail="Medication dose not found")
    if dose.status == "taken":
        return dose
    confirmed = dose.model_copy(update={"status": "taken", "confirmed_at": now()})
    repository.medication_doses[dose_id] = confirmed
    repository.save_medication_doses()
    repository.add_event(EventCreate(
        kind="routine", source="glasses", severity="info",
        summary=(
            f"Medicación confirmada: {dose.medication} a las "
            f"{dose.scheduled_at.astimezone(family_zone()).strftime('%H:%M')}"
        ),
        metadata={"dose_id": str(dose.id), "status": "taken"},
    ))
    return confirmed


@app.post("/v1/medication-tick", response_model=MedicationTickResult)
def medication_tick(
    at: Optional[datetime] = None, authorization: Optional[str] = Header(default=None),
) -> MedicationTickResult:
    require_auth(authorization)
    return run_medication_tick(at)


@app.post("/v1/memories", response_model=Memory, status_code=201)
def create_memory(request: MemoryCreate, authorization: Optional[str] = Header(default=None)) -> Memory:
    require_auth(authorization)
    if request.person_id is not None:
        person_or_404(request.person_id)
    memory = Memory(id=uuid4(), created_at=now(), **request.model_dump())
    repository.memories[memory.id] = memory
    repository.save_memories()
    return memory


@app.get("/v1/memories", response_model=list[Memory])
def list_memories(authorization: Optional[str] = Header(default=None)) -> list[Memory]:
    require_auth(authorization)
    return list(repository.memories.values())


COGNITIVE_TEMPLATES = {
    "recall": "Cuéntame con tus palabras: {summary}",
    "orientation": "¿Cuándo ocurrió esto? {summary}",
    "naming": "¿Quién o qué aparece en este recuerdo? {summary}",
}


@app.post("/v1/cognitive-exercises", response_model=CognitiveExercise, status_code=201)
def create_cognitive_exercise(
    request: CognitiveExerciseCreate, authorization: Optional[str] = Header(default=None),
) -> CognitiveExercise:
    require_auth(authorization)
    memory = repository.memories.get(request.memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    template = COGNITIVE_TEMPLATES.get(request.category, COGNITIVE_TEMPLATES["recall"])
    exercise = CognitiveExercise(
        id=uuid4(), memory_id=memory.id, category=request.category,
        question=template.format(summary=memory.summary), expected_answer=memory.summary,
        created_at=now(), status="pending",
    )
    repository.cognitive_exercises[exercise.id] = exercise
    repository.save_cognitive_exercises()
    return exercise


@app.get("/v1/cognitive-exercises", response_model=list[CognitiveExercise])
def list_cognitive_exercises(authorization: Optional[str] = Header(default=None)) -> list[CognitiveExercise]:
    require_auth(authorization)
    return sorted(repository.cognitive_exercises.values(), key=lambda item: item.created_at, reverse=True)


@app.get("/v1/cognitive-exercises/summary", response_model=CognitiveExerciseSummary)
def cognitive_exercise_summary(authorization: Optional[str] = Header(default=None)) -> CognitiveExerciseSummary:
    require_auth(authorization)
    items = list(repository.cognitive_exercises.values())
    completed = [item for item in items if item.status == "completed"]
    correct = sum(1 for item in completed if item.correct)
    accuracy = round(correct / len(completed) * 100, 1) if completed else 0.0
    return CognitiveExerciseSummary(
        total=len(items), pending=len(items) - len(completed),
        completed=len(completed), correct=correct, accuracy=accuracy,
    )


@app.post("/v1/cognitive-exercises/{exercise_id}/answer", response_model=CognitiveExercise)
def answer_cognitive_exercise(
    exercise_id: UUID, request: CognitiveExerciseAnswer, authorization: Optional[str] = Header(default=None),
) -> CognitiveExercise:
    require_auth(authorization)
    exercise = repository.cognitive_exercises.get(exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="Cognitive exercise not found")
    updated = exercise.model_copy(update={
        "status": "completed", "correct": request.correct,
        "answered_at": now(), "notes": request.notes,
    })
    repository.cognitive_exercises[exercise_id] = updated
    repository.save_cognitive_exercises()
    repository.add_event(EventCreate(
        kind="routine", source="portal", severity="info",
        summary=("Ejercicio cognitivo completado correctamente" if request.correct
                 else "Ejercicio cognitivo completado con dificultad"),
        metadata={"exercise_id": str(updated.id), "category": updated.category, "correct": request.correct},
    ))
    return updated


@app.post("/v1/cognitive-exercises/scheduled", response_model=CognitiveExercise, status_code=201)
def schedule_cognitive_exercise(
    request: ScheduledExerciseCreate, authorization: Optional[str] = Header(default=None),
) -> CognitiveExercise:
    require_auth(authorization)
    exercise = CognitiveExercise(
        id=uuid4(), memory_id=None, category=request.category,
        question=request.question.strip(), expected_answer=request.expected_answer.strip(),
        created_at=now(), status="pending", notes=request.notes, scheduled_at=request.scheduled_at,
    )
    repository.cognitive_exercises[exercise.id] = exercise
    repository.save_cognitive_exercises()
    return exercise


def run_exercise_tick(reference: Optional[datetime] = None) -> int:
    reference = reference or now()
    asked = 0
    for exercise in list(repository.cognitive_exercises.values()):
        if exercise.status != "pending" or exercise.scheduled_at is None or exercise.asked_at is not None:
            continue
        if exercise.scheduled_at <= reference:
            repository.enqueue_voice_reminder(exercise.id, exercise.question)
            repository.cognitive_exercises[exercise.id] = exercise.model_copy(update={"asked_at": reference})
            asked += 1
    if asked:
        repository.save_cognitive_exercises()
    return asked


@app.post("/v1/cognitive-exercises/tick")
def cognitive_exercise_tick(at: Optional[datetime] = None, authorization: Optional[str] = Header(default=None)) -> dict:
    require_auth(authorization)
    return {"asked": run_exercise_tick(at)}


@app.get("/v1/cognitive-exercises/report", response_model=CognitiveExerciseReport)
def cognitive_exercise_report(period: str = "daily", authorization: Optional[str] = Header(default=None)) -> CognitiveExerciseReport:
    require_auth(authorization)
    zone = family_zone()
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period)
    if days is None:
        raise HTTPException(status_code=422, detail="period debe ser daily, weekly o monthly")
    end = now().astimezone(zone)
    since = end - timedelta(days=days)
    items = [
        exercise for exercise in repository.cognitive_exercises.values()
        if exercise.answered_at is not None and exercise.answered_at.astimezone(zone) >= since
    ]
    completed = len(items)
    correct = sum(1 for exercise in items if exercise.correct)
    accuracy = round(correct / completed * 100, 1) if completed else 0.0
    label = {"daily": "diario", "weekly": "semanal", "monthly": "mensual"}[period]
    summary = (
        f"Informe {label}: {completed} ejercicios realizados y {correct} correctos ({accuracy}% de aciertos)."
        if completed else f"Informe {label}: sin ejercicios completados en este periodo."
    )
    return CognitiveExerciseReport(
        period=period, since=since, completed=completed, correct=correct, accuracy=accuracy, summary=summary,
    )


def calendar_reminder_message(event: CalendarEvent) -> str:
    momento = event.start_at.astimezone(family_zone()).strftime("%H:%M")
    if event.category == "medication":
        return f"Lembrete: {event.title} ás {momento}."
    return f"Acórdache: {event.title} ás {momento}."


def add_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def next_calendar_occurrence(event: CalendarEvent, reference: datetime) -> Optional[datetime]:
    """Siguiente inicio de un evento recurrente, o None si ya no se repite."""
    interval = max(1, event.recurrence_interval)
    base = event.start_at
    if event.recurrence == "daily":
        candidate = base + timedelta(days=interval)
        while candidate <= reference:
            candidate += timedelta(days=interval)
    elif event.recurrence == "weekly":
        weekdays = sorted({int(day) for day in (event.recurrence_weekdays or []) if 0 <= int(day) <= 6})
        if event.recurrence_weekdays and not weekdays:
            return None
        if weekdays:
            candidate = base
            for _ in range(366 * 2):
                candidate += timedelta(days=1)
                if candidate > reference and candidate.weekday() in weekdays:
                    break
            else:
                return None
        else:
            candidate = base + timedelta(weeks=interval)
            while candidate <= reference:
                candidate += timedelta(weeks=interval)
    elif event.recurrence == "monthly":
        candidate = add_months(base, interval)
        for _ in range(480):
            if candidate > reference:
                break
            candidate = add_months(candidate, interval)
        else:
            return None
    else:
        return None
    if event.recurrence_until is not None and candidate.astimezone(family_zone()).date() > event.recurrence_until:
        return None
    return candidate


def calendar_family_message(event: CalendarEvent) -> str:
    momento = event.start_at.astimezone(family_zone()).strftime("%H:%M")
    return f"Recordatorio de Faro: {event.title} a las {momento}."


def dispatch_calendar_family_reminder(message: str) -> dict:
    """Avisa por WhatsApp a la red de cuidados de un recordatorio de la familia."""
    contacts = enabled_alert_contacts()
    if not contacts:
        return {"status": "no_contact", "recipients_delivered": 0, "recipient_failures": ""}
    deliveries, failures = send_alert_to_contacts(contacts, EmergencyAlertCreate(
        kind="reminder", spoken_message=message, explicit_help_request=False,
    ))
    delivered = sum(1 for _, delivery in deliveries if delivery.message_id)
    if failures:
        logging.getLogger("aura.calendar").warning("aviso de agenda no entregado: %s", "; ".join(failures))
    return {
        "status": "sent" if delivered else "test_mode",
        "recipients_delivered": delivered,
        "recipient_failures": "; ".join(failures)[:300],
    }


@app.post("/v1/calendar-events", response_model=CalendarEvent, status_code=201)
def create_calendar_event(
    request: CalendarEventCreate, authorization: Optional[str] = Header(default=None),
) -> CalendarEvent:
    require_auth(authorization)
    event = CalendarEvent(id=uuid4(), created_at=now(), **request.model_dump())
    repository.calendar_events[event.id] = event
    repository.save_calendar_events()
    return event


@app.get("/v1/calendar-events", response_model=list[CalendarEvent])
def list_calendar_events(
    days: int = 30, authorization: Optional[str] = Header(default=None),
) -> list[CalendarEvent]:
    require_auth(authorization)
    limite = now() + timedelta(days=max(1, min(days, 365)))
    events = [
        event for event in repository.calendar_events.values()
        if event.enabled and event.start_at <= limite
    ]
    return sorted(events, key=lambda event: event.start_at)


@app.patch("/v1/calendar-events/{event_id}", response_model=CalendarEvent)
def update_calendar_event(
    event_id: UUID, request: CalendarEventUpdate, authorization: Optional[str] = Header(default=None),
) -> CalendarEvent:
    require_auth(authorization)
    event = repository.calendar_events.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    changes = request.model_dump(exclude_unset=True)
    if any(field in changes for field in ("start_at", "reminder_minutes_before", "enabled")):
        changes["reminded_at"] = None
    updated = event.model_copy(update=changes)
    repository.calendar_events[event_id] = updated
    repository.save_calendar_events()
    return updated


@app.delete("/v1/calendar-events/{event_id}", status_code=204, response_class=Response)
def delete_calendar_event(event_id: UUID, authorization: Optional[str] = Header(default=None)) -> Response:
    require_auth(authorization)
    repository.calendar_events.pop(event_id, None)
    repository.save_calendar_events()
    return Response(status_code=204)


def run_calendar_tick(reference: Optional[datetime] = None) -> CalendarTickResult:
    reference = medication_reference(reference)
    reminders: list[CalendarReminder] = []
    for event in list(repository.calendar_events.values()):
        if not event.enabled or event.reminded_at is not None:
            continue
        aviso = event.start_at - timedelta(minutes=event.reminder_minutes_before)
        if not (aviso <= reference <= event.start_at + timedelta(minutes=1)):
            continue
        message = calendar_reminder_message(event)
        reminders.append(CalendarReminder(
            event_id=event.id, title=event.title, category=event.category,
            start_at=event.start_at, message=message, for_patient=event.for_patient,
        ))
        delivery: dict = {"status": "queued", "recipients_delivered": 0, "recipient_failures": ""}
        if not event.for_patient:
            delivery = dispatch_calendar_family_reminder(calendar_family_message(event))
        else:
            repository.enqueue_voice_reminder(event.id, message)
        repository.add_event(EventCreate(
            kind="routine", source="backend", severity="info",
            summary=(
                f"Recordatorio de agenda: {event.title} a las "
                f"{event.start_at.astimezone(family_zone()).strftime('%H:%M')}"
            ),
            metadata={"calendar_event_id": str(event.id), "category": event.category,
                      "for_patient": event.for_patient,
                      "family_alert_status": delivery.get("status"),
                      "recipients_delivered": delivery.get("recipients_delivered", 0),
                      "recipient_failures": delivery.get("recipient_failures", "")},
        ))
        next_start = next_calendar_occurrence(event, reference) if event.recurrence != "none" else None
        if next_start is not None:
            repository.calendar_events[event.id] = event.model_copy(
                update={"start_at": next_start, "reminded_at": None}
            )
        else:
            repository.calendar_events[event.id] = event.model_copy(update={"reminded_at": reference})
    repository.save_calendar_events()
    return CalendarTickResult(at=reference, reminders=reminders)


@app.post("/v1/calendar-tick", response_model=CalendarTickResult)
def calendar_tick(
    at: Optional[datetime] = None, authorization: Optional[str] = Header(default=None),
) -> CalendarTickResult:
    require_auth(authorization)
    return run_calendar_tick(at)


GLASSES_NOT_WORN_DEDUP = timedelta(minutes=10)


@app.post("/v1/glasses/not-worn")
def glasses_not_worn(authorization: Optional[str] = Header(default=None)) -> dict:
    require_auth(authorization)
    last = repository.last_glasses_not_worn.get("default")
    if last is not None and now() - last < GLASSES_NOT_WORN_DEDUP:
        return {"status": "ignored"}
    repository.last_glasses_not_worn["default"] = now()
    repository.add_event(EventCreate(
        kind="routine", source="glasses", severity="attention",
        summary="El paciente no lleva las gafas puestas", metadata={"glasses_not_worn": True},
    ))
    repository.enqueue_voice_reminder(uuid4(), "Pon as gafas, por favor.")
    return {"status": "reminded"}


@app.get("/v1/voice-reminders", response_model=list[VoiceReminder])
def list_voice_reminders(authorization: Optional[str] = Header(default=None)) -> list[VoiceReminder]:
    require_auth(authorization)
    return [
        VoiceReminder(event_id=UUID(item["event_id"]), message=item["message"], created_at=item["created_at"])
        for item in repository.take_voice_reminders()
    ]


def start_tick_scheduler(interval_seconds: int = 20) -> None:
    """Hilo que ejecuta los ticks periódicamente para que los avisos actúen solos."""

    def loop() -> None:
        stop = threading.Event()
        while not stop.wait(max(15, interval_seconds)):
            try:
                run_medication_tick()
                run_calendar_tick()
                run_exercise_tick()
            except Exception as error:  # noqa: BLE001 - el planificador no debe morir
                logging.getLogger("aura.scheduler").warning("tick error: %s", error)

    threading.Thread(target=loop, daemon=True, name="aura-tick-scheduler").start()


@app.on_event("startup")
def _start_tick_scheduler() -> None:
    if os.getenv("AURA_TICK_SCHEDULER", "1").lower() in {"0", "false", "no", "off"}:
        return
    try:
        interval = int(os.getenv("AURA_TICK_INTERVAL_SECONDS", "20"))
    except ValueError:
        interval = 20
    start_tick_scheduler(interval)


class AcousticDetectionCreate(BaseModel):
    signal: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0, le=1)
    occurred_at: Optional[datetime] = None


class AcousticResponseCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    occurred_at: Optional[datetime] = None


acoustic_listening = EnvironmentalListeningEngine(ListeningConfig())
ACOUSTIC_ALERT_DEDUP = timedelta(minutes=10)


def dispatch_acoustic_escalation(escalation: dict) -> dict:
    """Send a cautious possible-symptom alert to the active care network."""
    contacts = enabled_alert_contacts()
    result = {
        "status": "no_contact", "recipients_attempted": 0, "recipients_delivered": 0,
        "recipient_failures": "",
    }
    if not contacts:
        return result
    result["recipients_attempted"] = len(contacts)
    deduplication_key = f"acoustic:{escalation['signal']}:{escalation['reason']}"
    previous = repository.last_auto_alert.get(deduplication_key)
    if previous and previous > now() - ACOUSTIC_ALERT_DEDUP:
        result["status"] = "suppressed_recent"
        return result
    repository.last_auto_alert[deduplication_key] = now()
    deliveries, failures = send_alert_to_contacts(contacts, EmergencyAlertCreate(
        kind=escalation["kind"], spoken_message=escalation["spoken_message"],
        explicit_help_request=escalation["explicit_help_request"],
    ))
    result["recipients_delivered"] = len(deliveries)
    result["recipient_failures"] = " | ".join(failures[:3])
    if not deliveries:
        result["status"] = "failed"
    else:
        result["status"] = "sent" if any(delivery.message_id for _, delivery in deliveries) else "test_mode"
    return result


def _apply_acoustic_outcome(outcome: dict, at: datetime, signal: str) -> dict:
    """Record the acoustic episode in the timeline and dispatch any escalation."""
    label = ACOUSTIC_SIGNAL_LABELS.get(signal, signal)
    action = outcome.get("action")
    if action == "ask":
        repository.add_event(EventCreate(
            kind="episode",
            summary=f"Posible {label}: se pregunta al paciente «{outcome['question']}»",
            source="glasses", severity="attention", occurred_at=at,
            metadata={"acoustic_signal": signal, "acoustic_stage": "check_in",
                      "episode_id": outcome.get("episode_id", "")},
        ))
        outcome["alert"] = None
    elif action == "escalate":
        escalation = outcome["escalation"]
        alert = dispatch_acoustic_escalation(escalation)
        repository.add_event(EventCreate(
            kind="hazard", summary=escalation["spoken_message"], source="glasses",
            severity="urgent", occurred_at=at,
            metadata={"acoustic_signal": escalation["signal"], "acoustic_stage": "escalated",
                      "acoustic_reason": escalation["reason"], "alert_status": alert["status"],
                      "recipients_attempted": alert["recipients_attempted"],
                      "recipients_delivered": alert["recipients_delivered"]},
        ))
        outcome["alert"] = alert
    return outcome


@app.post("/v1/acoustic-events")
def register_acoustic_event(request: AcousticDetectionCreate, authorization: Optional[str] = Header(default=None)) -> dict:
    """Report an acoustic detection from the glasses and get the next action."""
    require_auth(authorization)
    at = request.occurred_at or now()
    outcome = acoustic_listening.detect(request.signal, request.confidence, at)
    return _apply_acoustic_outcome(outcome, at, request.signal)


@app.post("/v1/acoustic-events/response")
def respond_to_acoustic_check_in(request: AcousticResponseCreate, authorization: Optional[str] = Header(default=None)) -> dict:
    """Register the patient's answer to the check-in question."""
    require_auth(authorization)
    at = request.occurred_at or now()
    signal = acoustic_listening.active_episode.signal if acoustic_listening.active_episode else ""
    outcome = acoustic_listening.respond(request.text, at)
    return _apply_acoustic_outcome(outcome, at, signal)


@app.post("/v1/acoustic-events/tick")
def tick_acoustic_listening(authorization: Optional[str] = Header(default=None)) -> dict:
    """Advance time-based logic (response timeout and limited retries)."""
    require_auth(authorization)
    at = now()
    signal = acoustic_listening.active_episode.signal if acoustic_listening.active_episode else ""
    outcome = acoustic_listening.tick(at)
    return _apply_acoustic_outcome(outcome, at, signal)


@app.get("/v1/acoustic-episodes")
def list_acoustic_episodes(authorization: Optional[str] = Header(default=None)) -> dict:
    require_auth(authorization)
    active = acoustic_listening.active_episode
    return {
        "active": active.snapshot() if active else None,
        "history": [episode.snapshot() for episode in reversed(acoustic_listening.history)],
    }
