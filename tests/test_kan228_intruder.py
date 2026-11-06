from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402


class _FakeProvider:
    def __init__(self, candidates=None, error: Exception | None = None) -> None:
        self.candidates = candidates or []
        self.error = error

    def search(self, image: bytes):
        if self.error is not None:
            raise self.error
        return self.candidates


class _Delivery:
    message_id = "wamid.test"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch):
    main._intruder_seen.clear()
    main._intruder_last_alert.clear()

    def fake_contacts():
        return [object()]

    monkeypatch.setattr(main, "enabled_alert_contacts", fake_contacts)
    yield
    main._intruder_seen.clear()
    main._intruder_last_alert.clear()


def test_no_face_does_not_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "face_provider", _FakeProvider(error=main.NoFaceDetectedError()))
    assert main.evaluate_camera_intruder(b"img", "escena")["status"] == "no_face"


def test_known_face_clears_and_never_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = main.FaceCandidate(person_id=main.PATIENT_FACE_ID, confidence=99.0)
    monkeypatch.setattr(main, "face_provider", _FakeProvider(candidates=[candidate]))
    for _ in range(4):
        result = main.evaluate_camera_intruder(b"img", "escena")
        assert result["status"] == "known"
        assert result["alert"] is False


def test_unknown_face_alerts_on_third_frame_with_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = main.FaceCandidate(person_id=uuid4(), confidence=97.0)
    monkeypatch.setattr(main, "face_provider", _FakeProvider(candidates=[candidate]))
    sent: list[bytes] = []

    def fake_send(contacts, alert, image=None):
        sent.append(image or b"")
        return [(contacts[0], _Delivery())], []

    monkeypatch.setattr(main, "send_alert_to_contacts", fake_send)

    first = main.evaluate_camera_intruder(b"img", "escena")
    second = main.evaluate_camera_intruder(b"img", "escena")
    third = main.evaluate_camera_intruder(b"img", "escena")
    assert first["alert"] is False and second["alert"] is False
    assert third["status"] == "intruder" and third["alert"] is True
    assert len(sent) == 1

    fourth = main.evaluate_camera_intruder(b"img", "escena")
    assert fourth["alert"] is False
    assert len(sent) == 1


def test_dry_run_never_sends_whatsapp(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = main.FaceCandidate(person_id=uuid4(), confidence=96.0)
    monkeypatch.setattr(main, "face_provider", _FakeProvider(candidates=[candidate]))

    def boom(*args, **kwargs):
        raise AssertionError("no debe enviar avisos en dry_run")

    monkeypatch.setattr(main, "send_alert_to_contacts", boom)
    for _ in range(3):
        result = main.evaluate_camera_intruder(b"img", "escena", dry_run=True)
    assert result["status"] == "intruder" and result["dry_run"] is True
    assert result["alert"] is False
