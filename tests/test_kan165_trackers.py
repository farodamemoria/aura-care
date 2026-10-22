"""KAN-165 - rastreadores vinculados (llaves, cartera) y su estado para la IA."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402

TOKEN = "kan165-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AURA_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    main.repository = main.InMemoryRepository()
    return TestClient(main.app)


def _create(client: TestClient, name: str = "Llaves", kind: str = "keys") -> dict:
    response = client.post("/v1/trackers", json={"name": name, "kind": kind}, headers=HEADERS)
    assert response.status_code == 201
    return response.json()


def test_crea_y_lista_rastreador(client: TestClient) -> None:
    tracker = _create(client)
    assert tracker["name"] == "Llaves"
    assert tracker["kind"] == "keys"
    assert tracker["status"] == "unknown"
    listed = client.get("/v1/trackers", headers=HEADERS).json()
    assert [item["id"] for item in listed] == [tracker["id"]]


def test_no_duplica_por_nombre(client: TestClient) -> None:
    _create(client)
    response = client.post("/v1/trackers", json={"name": "llaves", "kind": "keys"}, headers=HEADERS)
    assert response.status_code == 409


def test_actualiza_estado_y_lugar(client: TestClient) -> None:
    tracker = _create(client)
    response = client.post(
        f"/v1/trackers/{tracker['id']}/status",
        json={"status": "near", "place": "recibidor", "source": "ai"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "near"
    assert updated["place"] == "recibidor"
    assert updated["source"] == "ai"
    assert updated["last_seen_at"]


def test_busca_por_nombre_para_la_ia(client: TestClient) -> None:
    tracker = _create(client)
    client.post(
        f"/v1/trackers/{tracker['id']}/status",
        json={"status": "far", "place": "cocina", "source": "portal"},
        headers=HEADERS,
    )
    response = client.get("/v1/trackers/status", params={"name": "llaves"}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["place"] == "cocina"


def test_nombre_desconocido_da_404(client: TestClient) -> None:
    response = client.get("/v1/trackers/status", params={"name": "cartera"}, headers=HEADERS)
    assert response.status_code == 404


def test_estado_invalido_es_rechazado(client: TestClient) -> None:
    tracker = _create(client)
    response = client.post(
        f"/v1/trackers/{tracker['id']}/status", json={"status": "volando"}, headers=HEADERS,
    )
    assert response.status_code == 422


def test_persiste_tras_reinicio(client: TestClient) -> None:
    tracker = _create(client)
    client.post(
        f"/v1/trackers/{tracker['id']}/status",
        json={"status": "near", "place": "salon", "source": "manual"},
        headers=HEADERS,
    )
    main.repository = main.InMemoryRepository()
    listed = client.get("/v1/trackers", headers=HEADERS).json()
    assert len(listed) == 1
    assert listed[0]["place"] == "salon"


def test_estado_en_casa(client: TestClient) -> None:
    tracker = _create(client)
    response = client.post(
        f"/v1/trackers/{tracker['id']}/status",
        json={"status": "home", "source": "tracker"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "home"


def test_renombra_tracker(client: TestClient) -> None:
    tracker = _create(client)
    response = client.patch(
        f"/v1/trackers/{tracker['id']}", json={"name": "Llavero"}, headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Llavero"
