"""KAN-78 — Casos de uso / pruebas: persistir «Personas por aclarar» y su evidencia."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "integration-reviews-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JPEG = b"\xff\xd8\xff\xe0" + b"FACE-JPEG-EVIDENCE" * 8 + b"\xff\xd9"


@pytest.fixture()
def repo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_REVIEW_MEDIA_DIR", str(tmp_path / "review-images"))
    monkeypatch.setenv("AURA_REVIEW_SECRET", "test-review-secret")
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_CREDENTIAL_PEPPER", "test-pepper")
    return tmp_path


def _pending(age: timedelta = timedelta()) -> "main.ReviewItem":
    return main.ReviewItem(
        id=main.uuid4(), created_at=main.now() - age, status="pending",
        candidate_person_ids=[], confidences=[91.5],
    )


def _evidence(repo: "main.InMemoryRepository", review: "main.ReviewItem") -> Path:
    return repo.review_images_dir / f"{review.id}{main.REVIEW_IMAGE_SUFFIX}"


def test_review_and_image_survive_restart(repo_env: Path) -> None:
    first = main.InMemoryRepository()
    review = _pending()
    first.save_review(review)
    first.save_review_image(review.id, JPEG)

    second = main.InMemoryRepository()
    assert review.id in second.reviews
    assert second.reviews[review.id].status == "pending"
    assert second.reviews[review.id].confidences == [91.5]
    assert second.load_review_image(review.id) == JPEG


def test_evidence_is_encrypted_at_rest(repo_env: Path) -> None:
    repo = main.InMemoryRepository()
    review = _pending()
    repo.save_review_image(review.id, JPEG)
    raw = _evidence(repo, review).read_bytes()
    assert JPEG not in raw
    assert b"FACE-JPEG-EVIDENCE" not in raw
    assert repo.load_review_image(review.id) == JPEG


def test_resolve_and_expiry_delete_evidence(repo_env: Path) -> None:
    repo = main.InMemoryRepository()
    resolved = _pending()
    repo.save_review(resolved)
    repo.save_review_image(resolved.id, JPEG)
    repo.save_review(resolved.model_copy(update={"status": "resolved"}))
    repo.delete_review_evidence(resolved.id)
    assert not _evidence(repo, resolved).exists()

    expired = _pending(age=timedelta(hours=25))
    repo.save_review(expired)
    repo.save_review_image(expired.id, JPEG)
    repo.purge_expired_reviews()
    assert repo.reviews[expired.id].status == "expired"
    assert not _evidence(repo, expired).exists()


def test_save_review_is_idempotent(repo_env: Path) -> None:
    repo = main.InMemoryRepository()
    review = _pending()
    repo.save_review(review)
    repo.save_review(review)
    count = repo.event_db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    assert count == 1


def test_api_lifecycle_and_authorization(repo_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = main.InMemoryRepository()
    monkeypatch.setattr(main, "repository", repo)
    client = TestClient(main.app)
    review = _pending()
    repo.save_review(review)
    repo.save_review_image(review.id, JPEG)

    assert client.get(f"/v1/reviews/{review.id}/image").status_code == 401
    served = client.get(f"/v1/reviews/{review.id}/image", headers=HEADERS)
    assert served.status_code == 200 and served.content == JPEG
    assert served.headers["cache-control"] == "no-store, private"

    resolved = client.post(f"/v1/reviews/{review.id}/resolve", headers=HEADERS, json={"person_id": None})
    assert resolved.status_code == 200 and resolved.json()["status"] == "resolved"
    assert client.get(f"/v1/reviews/{review.id}/image", headers=HEADERS).status_code == 404
    listing = client.get("/v1/reviews", headers=HEADERS).json()
    assert listing[0]["id"] == str(review.id) and listing[0]["status"] == "resolved"


def test_expired_review_is_purged_by_listing(repo_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = main.InMemoryRepository()
    monkeypatch.setattr(main, "repository", repo)
    client = TestClient(main.app)
    review = _pending(age=timedelta(hours=25))
    repo.save_review(review)
    repo.save_review_image(review.id, JPEG)

    assert client.get(f"/v1/reviews/{review.id}/image", headers=HEADERS).status_code == 404
    listing = client.get("/v1/reviews", headers=HEADERS).json()
    assert any(item["id"] == str(review.id) and item["status"] == "expired" for item in listing)
    assert not _evidence(repo, review).exists()
