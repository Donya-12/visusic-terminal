"""Real-time spectrum analysis for the terminal equalizer.

The player hands us the samples that are currently being heard, so the bars
stay in sync with the music without any extra analysis thread.
"""

from __future__ import annotations

import numpy as np

# Tuned on normal music: band RMS values usually sit between -60 and -20 dBFS.
_DB_FLOOR = -68.0
_DB_TOP = -14.0
_GAMMA = 0.85
_RISE = 22.0
_FALL = 7.0
_PEAK_FALL = 0.75


def bands_for_width(width: int) -> int:
    return max(10, min(48, (max(width, 40) - 4) // 3))


class Spectrum:
    def __init__(self, samplerate: int, bands: int, window: int = 4096) -> None:
        self.samplerate = samplerate
        self.bands = bands
        self.window = window
        top = min(16000.0, samplerate * 0.45)
        self._edges = np.geomspace(45.0, top, bands + 1)
        self._window_fn = np.hanning(window).astype(np.float32)
        self._freqs = np.fft.rfftfreq(window, 1.0 / samplerate)
        self.values = np.zeros(bands, dtype=np.float32)
        self.peaks = np.zeros(bands, dtype=np.float32)

    def analyze(self, samples: np.ndarray) -> np.ndarray:
        window = self.window
        if len(samples) < window:
            padded = np.zeros(window, dtype=np.float32)
            padded[window - len(samples):] = samples
            samples = padded
        else:
            samples = samples[-window:]

        magnitude = np.abs(np.fft.rfft(samples * self._window_fn)) / (window / 2.0)
        power = magnitude * magnitude

        result = np.zeros(self.bands, dtype=np.float32)
        for i in range(self.bands):
            start = int(np.searchsorted(self._freqs, self._edges[i], side="left"))
            stop = int(np.searchsorted(self._freqs, self._edges[i + 1], side="left"))
            if stop <= start:
                stop = start + 1
            result[i] = np.sqrt(power[start:stop].mean())

        decibels = 20.0 * np.log10(result + 1e-9)
        level = np.clip((decibels - _DB_FLOOR) / (_DB_TOP - _DB_FLOOR), 0.0, 1.0)
        level = np.power(level, _GAMMA)
        level[level < 0.015] = 0.0
        return level.astype(np.float32)

    def update(self, samples: np.ndarray, dt: float) -> np.ndarray:
        target = self.analyze(samples)
        dt = max(1e-3, min(dt, 0.25))
        rise = 1.0 - np.exp(-dt * _RISE)
        fall = 1.0 - np.exp(-dt * _FALL)
        for i in range(self.bands):
            if target[i] > self.values[i]:
                self.values[i] += (target[i] - self.values[i]) * rise
            else:
                self.values[i] += (target[i] - self.values[i]) * fall

        decay = _PEAK_FALL * dt
        self.peaks = np.maximum(self.values, self.peaks - decay)
        return self.values.copy()

    def clear(self) -> None:
        self.values[:] = 0.0
        self.peaks[:] = 0.0
