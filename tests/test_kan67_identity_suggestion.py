"""KAN-67 - sugerencia de identidad probable desde el contexto de conversacion."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan67-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"FACE-JPEG" * 8 + b"\xff\xd9"


class ScriptedProvider:
    """Ninguna cara conocida: la revision se crea siempre."""

    def enroll(self, person_id: main.UUID, images: list[bytes]) -> int:
        return len(images)

    def search(self, image: bytes) -> list[main.FaceCandidate]:
        return []

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
    main.face_provider = ScriptedProvider()
    return TestClient(main.app)


def _files() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (f"frame{index}.jpg", JPEG, "image/jpeg")) for index in range(3)]


# --- motor de sugerencias (puro) ---

def test_contexto_claro_con_nombre_da_confianza_alta() -> None:
    suggestion = main.suggest_identity_from_transcripts(
        ["Hoy viene a verme mi hija Marta por la tarde"]
    )
    assert suggestion is not None
    assert suggestion["display_name"] == "Marta"
    assert suggestion["relationship"] == "hija"
    assert suggestion["confidence"] == "high"


def test_contexto_gallego_con_nombre() -> None:
    suggestion = main.suggest_identity_from_transcripts(["Vai vir a miña filla Sasha"])
    assert suggestion is not None
    assert suggestion["display_name"] == "Sasha"
    assert suggestion["relationship"] == "hija"


def test_relacion_sin_nombre_da_confianza_media() -> None:
    suggestion = main.suggest_identity_from_transcripts(["Estou esperando a mi nieta"])
    assert suggestion is not None
    assert suggestion["display_name"] is None
    assert suggestion["relationship"] == "nieta"
    assert suggestion["confidence"] == "medium"


def test_sin_contexto_no_sugiere() -> None:
    assert main.suggest_identity_from_transcripts([]) is None
    assert main.suggest_identity_from_transcripts(["Vamos a comer pronto"]) is None


def test_contexto_ambiguo_con_dos_nombres_no_sugiere() -> None:
    assert main.suggest_identity_from_transcripts([
        "Mi hija Marta me trae la compra",
        "mi hijo Pedro viene luego",
    ]) is None


def test_dos_relaciones_sin_nombre_no_sugiere() -> None:
    assert main.suggest_identity_from_transcripts([
        "viene mi hija",
        "tambien mi vecino",
    ]) is None


def test_contexto_acotado_a_200_caracteres() -> None:
    text = "x" * 300 + " mi hija Marta " + "y" * 300
    suggestion = main.suggest_identity_from_transcripts([text])
    assert suggestion is not None
    assert len(suggestion["context"]) <= 200


# --- flujo de revision + rechazo de hipotesis ---

def test_revision_lleva_sugerencia_y_se_puede_descartar(client: TestClient) -> None:
    main.repository.add_event(main.EventCreate(
        kind="conversation",
        summary="Mi hija Marta viene esta tarde",
        source="glasses",
        severity="info",
        metadata={"transcript": True, "speaker": "user"},
    ))
    body = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    assert body["status"] == "review_required"
    review = next(iter(main.repository.reviews.values()))
    assert review.suggestion is not None
    assert review.suggestion.display_name == "Marta"
    assert review.suggestion.confidence == "high"
    assert review.status == "pending"
    assert review.resolved_person_id is None
    dismissed = client.post(
        f"/v1/reviews/{review.id}/suggestion/dismiss", headers=HEADERS
    ).json()
    assert dismissed["suggestion"]["dismissed"] is True
    assert main.repository.reviews[review.id].suggestion.dismissed is True


def test_revision_sin_contexto_no_lleva_sugerencia(client: TestClient) -> None:
    body = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    assert body["status"] == "review_required"
    review = next(iter(main.repository.reviews.values()))
    assert review.suggestion is None


def test_sugerencia_no_confirma_ni_enrola(client: TestClient) -> None:
    person_id = main.UUID("22222222-2222-4222-8222-222222222222")
    main.repository.people[person_id] = main.Person(
        id=person_id, display_name="Marta", relationship="hija", consent_granted=True,
        created_at=main.now(),
    )
    main.repository.add_event(main.EventCreate(
        kind="conversation",
        summary="Viene mi hija Marta",
        source="glasses",
        severity="info",
        metadata={"transcript": True, "speaker": "user"},
    ))
    body = client.post("/v1/recognitions", headers=HEADERS, files=_files()).json()
    assert body["status"] == "review_required"
    review = next(iter(main.repository.reviews.values()))
    assert review.suggestion is not None
    assert review.suggestion.person_id == person_id
    assert review.status == "pending"
    assert review.resolved_person_id is None


def test_portal_muestra_la_sugerencia_y_el_descarte() -> None:
    js = (ROOT / "web" / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "assets" / "tokens.css").read_text(encoding="utf-8")
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "Posiblemente es su" in js
    assert "suggestion/dismiss" in js
    assert ".review-suggestion" in css
    assert re.search(r"/assets/app\.js\?v=\d+", html)
    assert re.search(r"/assets/tokens\.css\?v=\d+", html)
