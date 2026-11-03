"""KAN-35 — Pruebas con audio grabado, ruido ambiental y falsas alarmas.

Cubre el criterio 6: el WAV pasa por el analizador real (decodificación,
enventanado, FFT y clasificación) y el resultado alimenta el mismo motor que
usan los endpoints. Incluye una grabación real de ambiente de sala
(`tests/fixtures/audio/ambiente-sala-real.wav`) y ruido sintético determinista
(tos, grito, llanto, caída, televisión y ruido blanco).
"""

from __future__ import annotations

import importlib.util
import io
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.acoustic_audio import (  # noqa: E402
    AcousticAudioEvent,
    AudioFormatError,
    analyze_wav,
    decode_wav,
    feed_engine,
)
from app.environmental_listening import EnvironmentalListeningEngine, ListeningConfig  # noqa: E402

AUDIO_DIR = Path(__file__).resolve().parent / "fixtures" / "audio"
REAL_ROOM = AUDIO_DIR / "ambiente-sala-real.wav"
BASE = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)


def _load_generator():
    spec = importlib.util.spec_from_file_location("kan35_fixtures", AUDIO_DIR / "generate_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def generator():
    return _load_generator()


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory: pytest.TempPathFactory, generator) -> dict[str, Path]:
    return generator.build_fixtures(tmp_path_factory.mktemp("kan35-audio"))


def make_engine() -> EnvironmentalListeningEngine:
    return EnvironmentalListeningEngine(ListeningConfig())


def run(engine: EnvironmentalListeningEngine, path: Path) -> list[dict]:
    events, _, _ = analyze_wav(path.read_bytes())
    return feed_engine(engine, events, BASE)


def read_wav_samples(path: Path) -> tuple[list[float], int]:
    return decode_wav(path.read_bytes())


def write_wav(path: Path, samples: list[float], rate: int) -> Path:
    frames = bytearray()
    for value in samples:
        clipped = max(-1.0, min(1.0, value))
        frames += int(round(clipped * 32767)).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return path


def test_repeated_recorded_coughs_ask_exactly_once(fixtures: dict[str, Path]) -> None:
    engine = make_engine()
    outcomes = run(engine, fixtures["cough_repeated"])
    assert [outcome["action"] for outcome in outcomes] == ["listening", "listening", "ask"]
    assert outcomes[-1]["question"] == "¿Estás bien?"
    assert engine.active_episode is not None
    assert engine.active_episode.signal == "cough"


def test_isolated_recorded_cough_does_not_intervene(fixtures: dict[str, Path]) -> None:
    engine = make_engine()
    outcomes = run(engine, fixtures["cough_isolated"])
    assert outcomes and all(outcome["action"] == "listening" for outcome in outcomes)
    assert engine.active_episode is None


def test_loud_white_noise_is_not_a_false_alarm(fixtures: dict[str, Path]) -> None:
    engine = make_engine()
    assert run(engine, fixtures["white_noise"]) == []
    assert engine.active_episode is None


def test_background_television_is_not_a_false_alarm(fixtures: dict[str, Path]) -> None:
    engine = make_engine()
    assert run(engine, fixtures["babble"]) == []
    assert engine.active_episode is None


def test_real_room_recording_is_not_a_false_alarm() -> None:
    assert REAL_ROOM.exists(), "falta la grabación real de ambiente"
    engine = make_engine()
    assert run(engine, REAL_ROOM) == []
    assert engine.active_episode is None


def test_real_room_recording_with_coughs_asks(
    tmp_path: Path, generator, fixtures: dict[str, Path]
) -> None:
    samples, rate = read_wav_samples(REAL_ROOM)
    rng = generator.random.Random(3501)
    for at in (0.8, 2.9, 5.1):
        burst = generator.cough(rng)
        start = int(at * rate)
        for index, value in enumerate(burst):
            if start + index < len(samples):
                samples[start + index] += value
    mixed = write_wav(tmp_path / "sala-real-con-toses.wav", samples, rate)
    engine = make_engine()
    outcomes = run(engine, mixed)
    assert any(outcome["action"] == "ask" for outcome in outcomes)


def test_a_fall_is_checked_immediately(fixtures: dict[str, Path]) -> None:
    engine = make_engine()
    outcomes = run(engine, fixtures["fall"])
    assert outcomes[0]["action"] == "ask"
    assert outcomes[0]["reason"] == "immediate"
    assert engine.active_episode is not None and engine.active_episode.signal == "fall"


def test_shout_and_cry_are_classified(fixtures: dict[str, Path]) -> None:
    shout_events, _, _ = analyze_wav(fixtures["shout"].read_bytes())
    cry_events, _, _ = analyze_wav(fixtures["cry"].read_bytes())
    assert [event.signal for event in shout_events] == ["shout"]
    assert [event.signal for event in cry_events] == ["cry"]
    assert all(event.confidence >= 0.6 for event in shout_events + cry_events)


def test_short_and_silent_audio_returns_no_events(tmp_path: Path) -> None:
    short = write_wav(tmp_path / "silencio.wav", [0.0] * 800, 16000)
    events, duration, rate = analyze_wav(short.read_bytes())
    assert events == [] and duration < 0.1 and rate == 16000


def test_very_quiet_transients_are_not_events(tmp_path: Path, generator) -> None:
    rng = generator.random.Random(3511)
    samples = generator._noise(2.0, 0.0005, rng)
    generator._mix(samples, [value * 0.02 for value in generator.cough(rng)], 0.8)
    path = write_wav(tmp_path / "clic-muy-bajo.wav", samples, 16000)
    events, _, _ = analyze_wav(path.read_bytes())
    assert events == []


def test_invalid_audio_is_rejected() -> None:
    with pytest.raises(AudioFormatError):
        analyze_wav(b"no soy un wav")


def test_stereo_audio_is_downmixed(tmp_path: Path, generator) -> None:
    left = generator._noise(2.0, 0.004, generator.random.Random(9))
    right = generator._noise(2.0, 0.004, generator.random.Random(10))
    frames = bytearray()
    for a, b in zip(left, right):
        for value in (a, b):
            clipped = max(-1.0, min(1.0, value))
            frames += int(round(clipped * 32767)).to_bytes(2, "little", signed=True)
    path = tmp_path / "estereo.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(bytes(frames))
    events, duration, rate = analyze_wav(path.read_bytes())
    assert rate == 16000 and 1.9 <= duration <= 2.1
    assert events == []


def test_event_offsets_can_be_fed_in_order() -> None:
    engine = make_engine()
    events = [
        AcousticAudioEvent("cough", 0.9, 0.5, 0.3, -6.0),
        AcousticAudioEvent("cough", 0.9, 1.5, 0.3, -6.0),
        AcousticAudioEvent("cough", 0.9, 2.5, 0.3, -6.0),
    ]
    outcomes = feed_engine(engine, events, BASE)
    assert outcomes[-1]["action"] == "ask"
