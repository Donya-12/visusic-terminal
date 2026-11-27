"""Audio equalizer presets and a lightweight FIR design.

The filter is a 1025-tap linear-phase FIR applied in the audio callback with
overlap-save FFTs: no extra latency thread, no SciPy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BANDS = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
TAPS = 1025
MAX_GAIN = 12.0
CUSTOM_NAME = "custom"


@dataclass(frozen=True)
class EQPreset:
    name: str
    label: str
    description: str
    gains: tuple[float, ...]
    preamp: float = 0.0


PRESETS: dict[str, EQPreset] = {
    "flat": EQPreset(
        "flat", "Flat", "как в записи, без окраски",
        (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    ),
    "bass": EQPreset(
        "bass", "Bass Boost", "больше низов для наушников и колонок",
        (6, 5, 4, 2, 0, 0, -1, -1, -1, -2),
        preamp=-2.5,
    ),
    "vocal": EQPreset(
        "vocal", "Vocal", "вокал вперёд, меньше гула",
        (-3, -2, -1, 1, 3, 4, 3, 2, 0, -1),
        preamp=-1.5,
    ),
    "rock": EQPreset(
        "rock", "Rock", "плотные низы и яркие тарелки",
        (4, 3, 1, -1, -2, 0, 2, 3, 2, 1),
        preamp=-2.0,
    ),
    "electronic": EQPreset(
        "electronic", "Electronic", "клубный низ и воздух сверху",
        (3, 5, 4, 1, -1, 0, 1, 3, 4, 3),
        preamp=-2.0,
    ),
    "night": EQPreset(
        "night", "Night", "тише бас и мягкие верха",
        (-6, -4, -2, 0, 1, 2, 2, 1, 0, -2),
    ),
}

EQ_LIST = tuple(PRESETS.values())


def get_eq(name: str | None) -> EQPreset:
    if name and name in PRESETS:
        return PRESETS[name]
    return PRESETS["flat"]


def eq_names() -> list[str]:
    return list(PRESETS)


def clamp_gains(gains) -> tuple[float, ...]:
    values = list(gains)[:len(BANDS)]
    values += [0.0] * (len(BANDS) - len(values))
    result = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        number = round(max(-MAX_GAIN, min(MAX_GAIN, number)), 1)
        result.append(0.0 if number == 0 else number)
    return tuple(result)


def custom_preset(gains, label: str = "Custom",
                  description: str = "ручная настройка") -> EQPreset:
    values = clamp_gains(gains)
    preamp = -max(0.0, max(values)) * 0.5
    return EQPreset(CUSTOM_NAME, label, description, values, preamp)


def design_taps(preset: EQPreset, samplerate: int,
                taps: int = TAPS) -> np.ndarray | None:
    if all(abs(gain) < 0.01 for gain in preset.gains):
        return None

    half = taps // 2
    freqs = np.fft.rfftfreq(taps, 1.0 / samplerate)
    centers = np.log2(np.array(BANDS, dtype=np.float64))
    gains = np.array(preset.gains, dtype=np.float64) + preset.preamp
    positions = np.log2(np.maximum(freqs, 20.0))
    curve = np.interp(positions, centers, gains,
                      left=gains[0], right=gains[-1])
    magnitude = np.power(10.0, curve / 20.0)
    impulse = np.fft.irfft(magnitude, taps)
    shifted = np.roll(impulse, half)
    window = np.hanning(taps)
    return (shifted * window).astype(np.float32)
