"""KAN-154 - alta practica de persona conocida directamente desde 'Por aclarar'.

Contrato del endpoint POST /v1/reviews/{review_id}/create-person:
- 201 + Person cuando hay consentimiento explicito (consent_granted=true).
- 422 si falta el campo o si es false (nunca se asume consentimiento): sin persona ni enrolamiento.
- 404 si la revision no existe (con consentimiento true).
- Si el proveedor facial falla: la persona se crea sin enrollment_complete y la evidencia no se
  descarta hasta resolver la revision.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-kan154-token-5f3c9a7e1b6d8042c4e8a9f0d2b7c6"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xffkan154-review-jpeg"


class FaceRecorder:
    """face_provider de prueba: registra las llamadas y simula exito o fallo."""

    def __init__(self, result: int = 1, raises: bool = False) -> None:
        self.calls: list[tuple[object, list[bytes]]] = []
        self.result = result
        self.raises = raises

    def enroll(self, person_id: object, images: list[bytes]) -> int:
        self.calls.append((person_id, list(images)))
        if self.raises:
            raise RuntimeError("face provider down")
        return self.result

    def search(self, image: bytes) -> list[object]:
        return []

    def delete(self, person_id: object) -> None:
        return None


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_REVIEW_SECRET", base64.urlsafe_b64encode(b"0" * 32).decode())
    photos_dir = tmp_path / "people-photos"
    reviews_dir = tmp_path / "review-images"
    photos_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main.repository, "people_photo_dir", photos_dir, raising=False)
    monkeypatch.setattr(main.repository, "review_images_dir", reviews_dir, raising=False)
    main.repository.reviews.clear()
    main.repository.people.clear()
    return TestClient(main.app)


@pytest.fixture()
def face(monkeypatch: pytest.MonkeyPatch) -> FaceRecorder:
    recorder = FaceRecorder()
    monkeypatch.setattr(main, "face_provider", recorder, raising=False)
    return recorder


def _make_review(with_image: bool = True) -> object:
    review_id = uuid4()
    review = main.ReviewItem(
        id=review_id, created_at=main.now(), status="pending",
        candidate_person_ids=[], confidences=[],
    )
    main.repository.save_review(review)
    if with_image:
        main.repository.save_review_image(review_id, JPEG)
    return review_id


def _url(review_id: object) -> str:
    return f"/v1/reviews/{review_id}/create-person"


def test_crea_persona_con_consentimiento_y_enrola(
    client: TestClient, face: FaceRecorder
) -> None:
    review_id = _make_review()
    response = client.post(
        _url(review_id), headers=HEADERS,
        json={"display_name": "Bibiana", "relationship": "esposa", "consent_granted": True},
    )
    assert response.status_code == 201, response.text
    person = response.json()
    person_id = UUID(person["id"])
    assert person["display_name"] == "Bibiana"
    assert person["relationship"] == "esposa"
    assert person["consent_granted"] is True
    assert person["enrollment_complete"] is True
    assert person["enrollment_samples"] == 1
    assert person["profile_photo_available"] is True
    assert [call[1] for call in face.calls] == [[JPEG]]
    stored = main.repository.people[person_id]
    assert stored.enrollment_complete
    assert stored.profile_photo_available
    assert main.repository.person_photo(person_id) is not None
    resolved = main.repository.reviews[review_id]
    assert resolved.status == "resolved"
    assert resolved.resolved_person_id == person_id


def test_sin_campo_consentimiento_devuelve_422(
    client: TestClient, face: FaceRecorder
) -> None:
    review_id = _make_review()
    response = client.post(
        _url(review_id), headers=HEADERS,
        json={"display_name": "X", "relationship": "Y"},
    )
    assert response.status_code == 422
    assert main.repository.people == {}
    assert face.calls == []
    assert main.repository.reviews[review_id].status == "pending"


def test_consentimiento_false_devuelve_422_sin_crear_ni_enrolar(
    client: TestClient, face: FaceRecorder
) -> None:
    review_id = _make_review()
    response = client.post(
        _url(review_id), headers=HEADERS,
        json={"display_name": "X", "relationship": "Y", "consent_granted": False},
    )
    assert response.status_code == 422
    assert main.repository.people == {}
    assert face.calls == []
    assert main.repository.reviews[review_id].status == "pending"


def test_review_inexistente_devuelve_404(
    client: TestClient, face: FaceRecorder
) -> None:
    response = client.post(
        _url(uuid4()), headers=HEADERS,
        json={"display_name": "X", "relationship": "Y", "consent_granted": True},
    )
    assert response.status_code == 404
    assert main.repository.people == {}
    assert face.calls == []


def test_fallo_provider_no_marca_completo_ni_pierde_evidencia(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = FaceRecorder(raises=True)
    monkeypatch.setattr(main, "face_provider", recorder, raising=False)
    review_id = _make_review()
    response = client.post(
        _url(review_id), headers=HEADERS,
        json={"display_name": "Bibiana", "relationship": "esposa", "consent_granted": True},
    )
    assert response.status_code == 201, response.text
    person = response.json()
    person_id = UUID(person["id"])
    assert person["enrollment_complete"] is False
    assert person["enrollment_samples"] == 0
    assert person["profile_photo_available"] is False
    assert len(recorder.calls) == 1 and recorder.calls[0][1] == [JPEG]
    assert main.repository.people[person_id].enrollment_complete is False
    assert main.repository.person_photo(person_id) is None
    assert main.repository.reviews[review_id].status == "resolved"
    assert main.repository.load_review_image(review_id) is not None


def test_persona_sin_evidencia_no_enrola_pero_resuelve(
    client: TestClient, face: FaceRecorder
) -> None:
    review_id = _make_review(with_image=False)
    response = client.post(
        _url(review_id), headers=HEADERS,
        json={"display_name": "Bibiana", "relationship": "esposa", "consent_granted": True},
    )
    assert response.status_code == 201, response.text
    assert response.json()["enrollment_complete"] is False
    assert face.calls == []
    assert main.repository.reviews[review_id].status == "resolved"
