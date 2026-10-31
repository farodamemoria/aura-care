"""KAN-35 — Análisis de audio ambiental y puente con el motor de escucha.

Convierte un WAV de las gafas (micrófono ambiental) en detecciones acústicas
con señal, confianza y desplazamiento temporal, que después consume
`EnvironmentalListeningEngine` para decidir si pregunta o escala.

Todo es estándar de Python (sin numpy): decodificación PCM, enventanado,
FFT radix-2, rasgos por trama y clasificación determinista. Así el mismo
código corre en el backend y en las pruebas sin dependencias nuevas.

El analizador es deliberadamente conservador ante ruido continuo (televisión,
conversación de fondo, ventilador): solo emite una detección cuando hay un
evento con envolvente impulsiva o tonal clara. Un sonido aislado nunca genera
aviso porque el motor exige repetición (salvo caídas, que se comprueban al
momento).
"""

from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from .environmental_listening import EnvironmentalListeningEngine

MAX_AUDIO_BYTES = 8_000_000
SUPPORTED_SAMPLE_WIDTHS = (1, 2, 3, 4)


class AudioFormatError(ValueError):
    """El audio recibido no es un WAV PCM mono que podamos analizar."""


@dataclass(frozen=True)
class AudioAnalysisConfig:
    frame_seconds: float = 0.032
    hop_seconds: float = 0.016
    silence_dbfs: float = -52.0
    min_event_seconds: float = 0.06
    max_gap_seconds: float = 0.30
    max_event_seconds: float = 2.5
    noise_floor_percentile: float = 0.20
    min_snr_db: float = 9.0
    min_peak_dbfs: float = -30.0


@dataclass(frozen=True)
class AcousticAudioEvent:
    signal: str
    confidence: float
    offset_seconds: float
    duration_seconds: float
    peak_dbfs: float

    def as_dict(self) -> dict:
        return {
            "signal": self.signal,
            "confidence": round(self.confidence, 3),
            "offset_seconds": round(self.offset_seconds, 3),
            "duration_seconds": round(self.duration_seconds, 3),
            "peak_dbfs": round(self.peak_dbfs, 2),
        }


# ---------------------------------------------------------------- decodificación


def _decode_sample(raw: bytes, width: int) -> float:
    if width == 1:
        return (raw[0] - 128) / 128.0
    if width == 2:
        return int.from_bytes(raw, "little", signed=True) / 32768.0
    if width == 3:
        return int.from_bytes(raw, "little", signed=True) / 8388608.0
    if width == 4:
        return int.from_bytes(raw, "little", signed=True) / 2147483648.0
    raise AudioFormatError(f"ancho de muestra no soportado: {width}")


def decode_wav(data: bytes) -> tuple[list[float], int]:
    """Devuelve (muestras mono en [-1, 1], frecuencia de muestreo)."""
    if not data:
        raise AudioFormatError("audio vacío")
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.getnframes()
            raw = handle.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise AudioFormatError(f"WAV no válido: {exc}") from exc
    if channels < 1:
        raise AudioFormatError("canales no válidos")
    if width not in SUPPORTED_SAMPLE_WIDTHS:
        raise AudioFormatError(f"ancho de muestra no soportado: {width}")
    if rate <= 0:
        raise AudioFormatError("frecuencia de muestreo no válida")
    stride = width * channels
    usable = len(raw) - (len(raw) % stride)
    samples: list[float] = []
    append = samples.append
    if channels == 1:
        for offset in range(0, usable, width):
            append(_decode_sample(raw[offset:offset + width], width))
    else:
        for offset in range(0, usable, stride):
            total = 0.0
            for channel in range(channels):
                start = offset + channel * width
                total += _decode_sample(raw[start:start + width], width)
            append(total / channels)
    return samples, rate


# ------------------------------------------------------------------------ FFT


def _fft_power(frame: list[float]) -> list[float]:
    """Espectro de potencia (radix-2, in-place) de una trama de tamaño 2^n."""
    size = len(frame)
    re = list(frame)
    im = [0.0] * size
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
    length = 2
    while length <= size:
        angle = -2.0 * math.pi / length
        w_re = math.cos(angle)
        w_im = math.sin(angle)
        half = length >> 1
        for start in range(0, size, length):
            cur_re = 1.0
            cur_im = 0.0
            for k in range(half):
                a_re = re[start + k]
                a_im = im[start + k]
                b_re = re[start + k + half] * cur_re - im[start + k + half] * cur_im
                b_im = re[start + k + half] * cur_im + im[start + k + half] * cur_re
                re[start + k] = a_re + b_re
                im[start + k] = a_im + b_im
                re[start + k + half] = a_re - b_re
                im[start + k + half] = a_im - b_im
                next_re = cur_re * w_re - cur_im * w_im
                cur_im = cur_re * w_im + cur_im * w_re
                cur_re = next_re
        length <<= 1
    return [re[i] * re[i] + im[i] * im[i] for i in range(size // 2)]


def _hann(size: int) -> list[float]:
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (size - 1)) for i in range(size)]


@dataclass
class _Frame:
    start: float
    rms: float
    peak: float
    zcr: float
    low: float
    mid: float
    high: float
    centroid: float
    flatness: float

    @property
    def dbfs(self) -> float:
        return 20.0 * math.log10(max(self.rms, 1e-9))

    @property
    def crest(self) -> float:
        if self.rms <= 1e-9:
            return 0.0
        return self.peak / self.rms

    @property
    def tonality(self) -> float:
        return 1.0 - min(max(self.flatness, 0.0), 1.0)


def _analyse_frames(samples: list[float], rate: int, config: AudioAnalysisConfig) -> list[_Frame]:
    frame_size = max(64, int(rate * config.frame_seconds))
    if frame_size & (frame_size - 1):
        power = 1
        while power < frame_size:
            power <<= 1
        frame_size = power
    hop = max(1, int(rate * config.hop_seconds))
    window = _hann(frame_size)
    total = len(samples)
    frames: list[_Frame] = []
    start = 0
    while start + frame_size <= total:
        chunk = samples[start:start + frame_size]
        energy = 0.0
        peak = 0.0
        crossings = 0
        previous = chunk[0]
        for index, value in enumerate(chunk):
            energy += value * value
            magnitude = abs(value)
            if magnitude > peak:
                peak = magnitude
            if index and ((value >= 0) != (previous >= 0)):
                crossings += 1
            previous = value
        rms = math.sqrt(energy / frame_size)
        windowed = [chunk[i] * window[i] for i in range(frame_size)]
        power = _fft_power(windowed)
        bins = len(power)
        nyquist = rate / 2.0
        total_power = sum(power) or 1e-12
        low = mid = high = 0.0
        weighted = 0.0
        log_sum = 0.0
        for bin_index, value in enumerate(power):
            frequency = (bin_index + 1) * nyquist / bins
            if frequency < 300.0:
                low += value
            elif frequency < 2000.0:
                mid += value
            else:
                high += value
            weighted += frequency * value
            log_sum += math.log(value + 1e-12)
        mean_power = total_power / bins
        flatness = math.exp(log_sum / bins) / (mean_power + 1e-12)
        frames.append(_Frame(
            start=start / rate,
            rms=rms,
            peak=peak,
            zcr=crossings / frame_size,
            low=low / total_power,
            mid=mid / total_power,
            high=high / total_power,
            centroid=weighted / total_power,
            flatness=flatness,
        ))
        start += hop
    return frames


# --------------------------------------------------------------- clasificación


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _classify(duration: float, peak_dbfs: float, snr: float, crest: float, zcr: float,
              low: float, mid: float, high: float, centroid: float, tonality: float) -> Optional[tuple[str, float]]:
    """Devuelve (señal, confianza) o None si el evento no es relevante."""
    if snr < 6.0:
        return None

    if low >= 0.55 and duration <= 0.55 and crest >= 3.0 and centroid < 320.0:
        return "fall", _clamp(0.72 + 0.02 * (snr - 12.0), 0.72, 0.95)

    if 0.05 <= duration <= 1.2 and high >= 0.12 and crest >= 2.0 and snr >= 10.0:
        return "cough", _clamp(0.62 + 0.02 * (snr - 10.0) + 0.02 * (crest - 2.0), 0.62, 0.97)

    if (duration >= 0.6 and centroid >= 620.0 and mid >= 0.50 and high <= 0.15
            and tonality >= 0.50 and crest <= 3.0 and snr >= 10.0):
        return "cry", _clamp(0.55 + 0.02 * (snr - 10.0), 0.55, 0.85)

    if (0.25 <= duration <= 3.0 and 200.0 <= centroid <= 700.0 and mid >= 0.28
            and crest <= 3.2 and zcr >= 0.02 and snr >= 12.0):
        return "shout", _clamp(0.58 + 0.02 * (snr - 12.0), 0.58, 0.9)

    if (duration >= 0.35 and (low + mid) >= 0.70 and centroid <= 450.0 and zcr <= 0.09
            and crest <= 3.2 and tonality >= 0.35 and snr >= 10.0):
        return "groan", _clamp(0.55 + 0.02 * (snr - 10.0), 0.55, 0.85)

    return None


def analyze_wav(data: bytes, config: Optional[AudioAnalysisConfig] = None) -> tuple[list[AcousticAudioEvent], float, int]:
    """Analiza un WAV y devuelve (eventos, duración en segundos, frecuencia)."""
    config = config or AudioAnalysisConfig()
    samples, rate = decode_wav(data)
    if len(samples) < rate * 0.1:
        return [], len(samples) / rate, rate
    frames = _analyse_frames(samples, rate, config)
    if not frames:
        return [], len(samples) / rate, rate

    levels = sorted(frame.dbfs for frame in frames)
    index = min(len(levels) - 1, max(0, int(config.noise_floor_percentile * len(levels))))
    noise_floor = levels[index]
    threshold = max(config.silence_dbfs, noise_floor + config.min_snr_db)

    events: list[AcousticAudioEvent] = []
    total_seconds = len(samples) / rate

    def add_event(segment: list[_Frame]) -> None:
        if not segment:
            return
        duration = (segment[-1].start + config.frame_seconds) - segment[0].start
        touches_edge = (segment[0].start < 0.02
                        or (segment[-1].start + config.frame_seconds) > total_seconds - 0.02)
        if not (config.min_event_seconds <= duration <= config.max_event_seconds) or touches_edge:
            return
        peak = max(frame.peak for frame in segment)
        peak_dbfs = 20.0 * math.log10(max(peak, 1e-9))
        if peak_dbfs < config.min_peak_dbfs:
            return
        snr = peak_dbfs - noise_floor
        rms = math.sqrt(sum(frame.rms * frame.rms for frame in segment) / len(segment))
        crest = (peak / rms) if rms > 1e-9 else 0.0
        weight = sum(frame.rms for frame in segment) or 1e-12
        zcr = sum(frame.zcr * frame.rms for frame in segment) / weight
        low = sum(frame.low * frame.rms for frame in segment) / weight
        mid = sum(frame.mid * frame.rms for frame in segment) / weight
        high = sum(frame.high * frame.rms for frame in segment) / weight
        centroid = sum(frame.centroid * frame.rms for frame in segment) / weight
        tonality = sum(frame.tonality * frame.rms for frame in segment) / weight
        classified = _classify(duration, peak_dbfs, snr, crest, zcr, low, mid, high, centroid, tonality)
        if classified is None:
            return
        signal, confidence = classified
        events.append(AcousticAudioEvent(
            signal=signal,
            confidence=confidence,
            offset_seconds=segment[0].start,
            duration_seconds=duration,
            peak_dbfs=peak_dbfs,
        ))

    def split_region(region: list[_Frame]) -> list[list[_Frame]]:
        """Separa golpes aislados dentro de un fondo activo (p. ej. tos sobre ruido).

        Tras cerrar un golpe se descarta su cola de decaimiento hasta que la
        energía vuelve a subir por encima de un umbral de rearme; así una sola
        tos no se cuenta dos veces.
        """
        segments: list[list[_Frame]] = []
        current: list[_Frame] = []
        peak = -math.inf
        gate = -math.inf
        armed = True
        below_run = 0
        needed = max(1, int(0.08 / config.hop_seconds))
        for frame in region:
            if not armed:
                if frame.dbfs < gate:
                    continue
                armed = True
            if current and frame.dbfs < peak - 12.0:
                below_run += 1
                if below_run >= needed:
                    while current and current[-1].dbfs < peak - 12.0:
                        current.pop()
                    if current:
                        segments.append(current)
                    gate = peak - 10.0
                    current = []
                    peak = -math.inf
                    below_run = 0
                    armed = False
                    continue
            else:
                below_run = 0
            current.append(frame)
            peak = max(peak, frame.dbfs)
        if current:
            segments.append(current)
        return segments

    regions: list[list[_Frame]] = []
    region: list[_Frame] = []
    last_end = 0.0
    for frame in frames:
        if frame.dbfs >= threshold:
            if region and frame.start - (region[-1].start + config.frame_seconds) > config.max_gap_seconds:
                regions.append(region)
                region = []
            region.append(frame)
            last_end = frame.start
        elif region and frame.start - last_end > config.max_gap_seconds:
            regions.append(region)
            region = []
    if region:
        regions.append(region)

    for region in regions:
        for segment in split_region(region):
            add_event(segment)

    events.sort(key=lambda event: event.offset_seconds)
    return events, len(samples) / rate, rate


# ------------------------------------------------------------------- puente


def feed_engine(engine: EnvironmentalListeningEngine, events: Iterable[AcousticAudioEvent],
                started_at: datetime) -> list[dict]:
    """Inyecta los eventos del audio en el motor, en orden temporal."""
    outcomes: list[dict] = []
    for event in events:
        at = started_at + timedelta(seconds=event.offset_seconds)
        outcomes.append(engine.detect(event.signal, event.confidence, at))
    return outcomes
