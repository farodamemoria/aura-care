"""Casos de uso: alta de caras de personas conocidas con 1 a 5 fotografías."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "people-enroll-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"FACE-JPEG" * 8 + b"\xff\xd9"
PERSON_ID = main.UUID("22222222-2222-4222-8222-222222222222")


class RecordingProvider:
    def __init__(self, indexed: int | None = None) -> None:
        self.indexed = indexed
        self.deleted: list[main.UUID] = []
        self.enrolled: list[int] = []

    def enroll(self, person_id: main.UUID, images: list[bytes]) -> int:
        self.enrolled.append(len(images))
        return len(images) if self.indexed is None else self.indexed

    def search(self, image: bytes) -> list[main.FaceCandidate]:
        return []

    def delete(self, person_id: main.UUID) -> None:
        self.deleted.append(person_id)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_MEDIA_DIR", str(tmp_path / "person-photos"))
    main.repository = main.InMemoryRepository()
    main.repository.people[PERSON_ID] = main.Person(
        id=PERSON_ID, display_name="Ana", relationship="filla", consent_granted=True,
        created_at=main.now(),
    )
    return TestClient(main.app)


def _files(count: int) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (f"face{index}.jpg", JPEG, "image/jpeg")) for index in range(count)]


def test_single_photo_is_enough(client: TestClient) -> None:
    main.face_provider = RecordingProvider()
    response = client.post(f"/v1/people/{PERSON_ID}/face-samples", headers=HEADERS, files=_files(1))
    assert response.status_code == 200
    body = response.json()
    assert body["enrollment_samples"] == 1
    assert body["enrollment_complete"] is True


def test_up_to_five_photos_are_accepted(client: TestClient) -> None:
    main.face_provider = RecordingProvider()
    response = client.post(f"/v1/people/{PERSON_ID}/face-samples", headers=HEADERS, files=_files(5))
    assert response.status_code == 200
    assert response.json()["enrollment_samples"] == 5


def test_no_photo_is_rejected(client: TestClient) -> None:
    main.face_provider = RecordingProvider()
    assert client.post(f"/v1/people/{PERSON_ID}/face-samples", headers=HEADERS).status_code == 422


def test_more_than_five_photos_are_rejected(client: TestClient) -> None:
    main.face_provider = RecordingProvider()
    response = client.post(f"/v1/people/{PERSON_ID}/face-samples", headers=HEADERS, files=_files(6))
    assert response.status_code == 422


def test_unusable_face_is_rejected_and_nothing_indexed(client: TestClient) -> None:
    provider = RecordingProvider(indexed=0)
    main.face_provider = provider
    response = client.post(f"/v1/people/{PERSON_ID}/face-samples", headers=HEADERS, files=_files(2))
    assert response.status_code == 422
    assert provider.deleted.count(PERSON_ID) >= 2


def test_reenrolling_replaces_previous_faces(client: TestClient) -> None:
    provider = RecordingProvider()
    main.face_provider = provider
    client.post(f"/v1/people/{PERSON_ID}/face-samples", headers=HEADERS, files=_files(5))
    client.post(f"/v1/people/{PERSON_ID}/face-samples", headers=HEADERS, files=_files(2))
    assert provider.deleted.count(PERSON_ID) == 2
