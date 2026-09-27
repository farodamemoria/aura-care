"""El prompt del chat familiar debe incluir las personas conocidas y la red de cuidados."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main as main  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_prompt_includes_known_people(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AURA_EVENT_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AURA_DATA_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("AURA_OPENAI_API_KEY", "test-key")
    repository = main.InMemoryRepository()
    monkeypatch.setattr(main, "repository", repository)
    repository.people[main.uuid4()] = main.Person(
        id=main.uuid4(), display_name="Ana", relationship="filla", consent_granted=True,
        created_at=main.now(),
    )
    captured: dict = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"output": [{"content": [{"type": "output_text", "text": "ok"}]}]})

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    main.openai_family_answer("Dime el nombre de mis familiares", [], "es")
    assert "Ana" in captured["payload"]["instructions"]
    assert "Personas conocidas" in captured["payload"]["instructions"]
