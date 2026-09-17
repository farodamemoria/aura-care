"""KAN-111 — pruebas: no crear «Personas por aclarar» para conocidos ni no-humanos."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan111-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"FACE-JPEG" * 8 + b"\xff\xd9"
PERSON_ID = main.UUID("11111111-1111-4111-8111-111111111111")


class ScriptedProvider:
    """Devuelve resultados/comportamientos por frame, en orden."""

    def __init__(self, per_frame: list[object]) -> None:
        self.per_frame = list(per_frame)

    def enroll(self, person_id: main.UUID, images: list[bytes]) -> int:
        return len(images)

    def search(self, image: bytes) -> list[main.FaceCandidate]:
        outcome = self.per_frame.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def delete(self, person_id: main.UUID) -> None:
        return None


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    main.repository = main.InMemoryRepository()
    main.repository.people[PERSON_ID] = main.Person(
        id=PERSON_ID, display_name="Ana", relationship="filla", consent_granted=True,
        created_at=main.now(),
    )
    return TestClient(main.app)


def _files() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (f"frame{index}.jpg", JPEG, "image/jpeg")) for index in range(3)]


def _match(confidence: float) -> main.FaceCandidate:
    return main.FaceCandidate(person_id=PERSON_ID, confidence=confidence)


def test_unknown_face_creates_review(client: TestClient) -> None:
    main.face_provider = ScriptedProvider([[], [], []])
    response = client.post("/v1/recognitions", headers=HEADERS, files=_files())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "review_required"
    assert len(main.repository.reviews) == 1


def test_repeated_unknown_face_creates_only_one_review(client: TestClient) -> None:
    main.face_provider = ScriptedProvider([[], [], [], [], [], []])
    first = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    second = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    assert first["status"] == "review_required"
    assert second["status"] == "unknown"
    assert len(main.repository.reviews) == 1


def test_non_human_frames_do_not_create_review(client: TestClient) -> None:
    main.face_provider = ScriptedProvider([main.NoFaceDetectedError()] * 3)
    body = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    assert body["status"] == "unknown"
    assert main.repository.reviews == {}


def test_known_person_without_consensus_does_not_create_review(client: TestClient) -> None:
    main.face_provider = ScriptedProvider([[_match(96.0)], [], []])
    body = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    assert body["status"] == "unknown"
    assert main.repository.reviews == {}


def test_known_person_with_consensus_is_confirmed(client: TestClient) -> None:
    main.face_provider = ScriptedProvider([[_match(99.0)], [_match(99.0)], [_match(99.0)]])
    body = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    assert body["status"] == "confirmed"
    assert body["person"]["display_name"] == "Ana"
    assert main.repository.reviews == {}


class _InvalidParameter(Exception):
    pass


class FakeRekognitionClient:
    exceptions = type("Exceptions", (), {"InvalidParameterException": _InvalidParameter})

    def __init__(self, response: dict) -> None:
        self.response = response

    def search_faces_by_image(self, **kwargs: object) -> dict:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _rekognition(response: object) -> main.RekognitionFaceProvider:
    provider = main.RekognitionFaceProvider.__new__(main.RekognitionFaceProvider)
    provider.collection_id = "faro-faces"
    provider.client = FakeRekognitionClient(response)  # type: ignore[assignment]
    return provider


def test_rekognition_rejects_spurious_low_confidence_face() -> None:
    provider = _rekognition({"SearchedFaceConfidence": 55.0, "FaceMatches": []})
    with pytest.raises(main.NoFaceDetectedError):
        provider.search(JPEG)


def test_rekognition_rejects_image_without_faces() -> None:
    provider = _rekognition(_InvalidParameter())
    with pytest.raises(main.NoFaceDetectedError):
        provider.search(JPEG)


def test_rekognition_returns_matches_for_real_face() -> None:
    provider = _rekognition(
        {
            "SearchedFaceConfidence": 99.9,
            "FaceMatches": [{"Face": {"ExternalImageId": str(PERSON_ID)}, "Similarity": 98.4}],
        }
    )
    matches = provider.search(JPEG)
    assert matches == [main.FaceCandidate(person_id=PERSON_ID, confidence=98.4)]
