"""KAN-94 tests for the self-hosted APK download.

Covers:
- the portal download button points to the backend endpoint (no Google Drive);
- the endpoint returns 404 when the APK file is not present;
- the endpoint serves the APK with the Android package media type when present.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(main.app)


def test_download_button_points_to_self_hosted_apk() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "/download/faro.apk" in html
    assert "drive.usercontent.google.com" not in html
    assert "drive.google.com" not in html


def test_apk_download_404_when_missing(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "downloads_dir", tmp_path)
    response = client.get("/download/faro.apk")
    assert response.status_code == 404


def test_apk_download_serves_apk(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    apk = tmp_path / "faro.apk"
    apk.write_bytes(b"PK\x03\x04fake-apk-content")
    monkeypatch.setattr(main, "downloads_dir", tmp_path)
    response = client.get("/download/faro.apk")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.android.package-archive")
    assert response.content == b"PK\x03\x04fake-apk-content"
