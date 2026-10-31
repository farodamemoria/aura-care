"""Genera los WAV de prueba de KAN-35 de forma determinista.

Los sonidos sintéticos imitan la envolvente y el espectro de una tos, un golpe,
un grito y un llanto, y se mezclan con ruido de sala. Se generan en una carpeta
temporal durante las pruebas para no versionar binarios grandes; el único WAV
versionado es la grabación real de ambiente (`ambiente-sala-real.wav`).

Uso manual:
    python tests/fixtures/audio/generate_fixtures.py <carpeta-destino>
"""

from __future__ import annotations

import math
import random
import sys
import wave
from pathlib import Path

RATE = 16000


def _write(path: Path, samples: list[float], rate: int = RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _silence(seconds: float) -> list[float]:
    return [0.0] * int(seconds * RATE)


def _noise(seconds: float, amplitude: float, rng: random.Random) -> list[float]:
    return [rng.uniform(-amplitude, amplitude) for _ in range(int(seconds * RATE))]


def _mix(base: list[float], extra: list[float], at: float) -> None:
    start = int(at * RATE)
    for index, value in enumerate(extra):
        position = start + index
        if position >= len(base):
            break
        base[position] += value


def cough(rng: random.Random, seconds: float = 0.42) -> list[float]:
    """Tos: ruido de banda ancha con ataque rápido y caída exponencial."""
    count = int(seconds * RATE)
    samples: list[float] = []
    previous = 0.0
    for index in range(count):
        t = index / RATE
        attack = min(1.0, t / 0.012)
        decay = math.exp(-t / 0.11)
        value = rng.uniform(-1.0, 1.0)
        value = value - previous * 0.35
        previous = rng.uniform(-1.0, 1.0)
        samples.append(value * attack * decay * 0.42)
    return samples


def thud(rng: random.Random, seconds: float = 0.30) -> list[float]:
    """Golpe/caída: impulso grave con caída rápida."""
    count = int(seconds * RATE)
    samples: list[float] = []
    for index in range(count):
        t = index / RATE
        decay = math.exp(-t / 0.06)
        tone = math.sin(2.0 * math.pi * 72.0 * t) + 0.4 * math.sin(2.0 * math.pi * 144.0 * t)
        samples.append(tone * decay * 0.55 + rng.uniform(-0.05, 0.05) * decay)
    return samples


def shout(rng: random.Random, seconds: float = 0.9) -> list[float]:
    """Grito: voz sostenida con armónicos y modulación."""
    count = int(seconds * RATE)
    samples: list[float] = []
    for index in range(count):
        t = index / RATE
        envelope = min(1.0, t / 0.05) * min(1.0, (seconds - t) / 0.15)
        vibrato = 1.0 + 0.02 * math.sin(2.0 * math.pi * 5.0 * t)
        value = (math.sin(2.0 * math.pi * 190.0 * vibrato * t)
                 + 0.6 * math.sin(2.0 * math.pi * 380.0 * vibrato * t)
                 + 0.35 * math.sin(2.0 * math.pi * 570.0 * vibrato * t))
        samples.append(value * envelope * 0.24 + rng.uniform(-0.005, 0.005))
    return samples


def cry(rng: random.Random, seconds: float = 1.4) -> list[float]:
    """Llanto: tono agudo con vibrato lento."""
    count = int(seconds * RATE)
    samples: list[float] = []
    for index in range(count):
        t = index / RATE
        envelope = min(1.0, t / 0.12) * min(1.0, (seconds - t) / 0.2)
        vibrato = 1.0 + 0.04 * math.sin(2.0 * math.pi * 3.2 * t)
        value = math.sin(2.0 * math.pi * 620.0 * vibrato * t) + 0.3 * math.sin(2.0 * math.pi * 1240.0 * vibrato * t)
        samples.append(value * envelope * 0.2 + rng.uniform(-0.004, 0.004))
    return samples


def babble(rng: random.Random, seconds: float = 6.0) -> list[float]:
    """Conversación/televisión de fondo: ruido de banda media modulado."""
    count = int(seconds * RATE)
    samples: list[float] = []
    lowpass = 0.0
    for index in range(count):
        t = index / RATE
        lowpass = 0.92 * lowpass + 0.08 * rng.uniform(-1.0, 1.0)
        envelope = 0.45 + 0.35 * abs(math.sin(2.0 * math.pi * 0.7 * t)) + 0.1 * math.sin(2.0 * math.pi * 3.1 * t)
        samples.append(lowpass * envelope * 0.55)
    return samples


def build_fixtures(target: Path) -> dict[str, Path]:
    target = Path(target)
    rng = random.Random(35)
    files: dict[str, Path] = {}

    # Tres toses separadas dentro de la ventana de 90 s.
    samples = _noise(6.0, 0.004, rng)
    for at in (0.7, 2.8, 5.0):
        _mix(samples, cough(rng), at)
    files["cough_repeated"] = _write(target / "tos-repetida-sintetica.wav", samples)

    # Una sola tos: no debe intervenir.
    samples = _noise(4.0, 0.004, rng)
    _mix(samples, cough(rng), 1.5)
    files["cough_isolated"] = _write(target / "tos-aislada-sintetica.wav", samples)

    # Ruido blanco fuerte continuo: falsa alarma clásica.
    files["white_noise"] = _write(target / "ruido-blanco-fuerte.wav", _noise(5.0, 0.30, rng))

    # Conversación/televisión de fondo: tampoco debe alertar.
    files["babble"] = _write(target / "television-fondo-sintetica.wav", babble(rng))

    # Dos golpes: una caída se comprueba al momento (pregunta), sin diagnóstico.
    samples = _noise(3.5, 0.004, rng)
    _mix(samples, thud(rng), 1.0)
    files["fall"] = _write(target / "caida-sintetica.wav", samples)

    # Grito y llanto con ruido de sala.
    samples = _noise(3.0, 0.004, rng)
    _mix(samples, shout(rng), 1.2)
    files["shout"] = _write(target / "grito-sintetico.wav", samples)
    samples = _noise(3.5, 0.004, rng)
    _mix(samples, cry(rng), 1.0)
    files["cry"] = _write(target / "llanto-sintetico.wav", samples)

    return files


if __name__ == "__main__":
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    for name, path in build_fixtures(destination).items():
        print(f"{name}: {path}")
