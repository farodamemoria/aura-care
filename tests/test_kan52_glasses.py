"""KAN-52 — pruebas: detección de "no lleva las gafas"."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan52-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    main.repository.last_glasses_not_worn.clear()
    main.repository.event_db.execute("DELETE FROM voice_reminders")
    main.repository.event_db.commit()
    return TestClient(main.app)


def test_not_worn_reminds_once_and_requires_auth(client: TestClient) -> None:
    assert client.post("/v1/glasses/not-worn").status_code == 401
    assert client.post("/v1/glasses/not-worn", headers=HEADERS).json()["status"] == "reminded"
    queue = client.get("/v1/voice-reminders", headers=HEADERS).json()
    assert len(queue) == 1 and "gafas" in queue[0]["message"]
    assert client.post("/v1/glasses/not-worn", headers=HEADERS).json()["status"] == "ignored"
