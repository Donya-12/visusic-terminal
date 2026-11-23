from __future__ import annotations

import unittest

import numpy as np

from visusic.spectrum import Spectrum, bands_for_width


def tone(frequency: float, samplerate: int = 48000, size: int = 4096) -> np.ndarray:
    t = np.arange(size) / samplerate
    return (0.5 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


class SpectrumTests(unittest.TestCase):
    def test_tone_lands_in_the_right_band(self) -> None:
        spectrum = Spectrum(48000, 40)
        values = spectrum.analyze(tone(1000.0))

        edges = np.geomspace(45.0, 48000 * 0.45, 41)
        expected = int(np.searchsorted(edges, 1000.0) - 1)
        self.assertLessEqual(abs(int(values.argmax()) - expected), 1)
        self.assertGreater(float(values.max()), 0.65)

        others = np.delete(values, values.argmax())
        self.assertLess(float(others.mean()), 0.2)

    def test_silence_is_flat(self) -> None:
        spectrum = Spectrum(44100, 24)
        values = spectrum.analyze(np.zeros(4096, dtype=np.float32))
        self.assertTrue(np.all(values == 0.0))
        self.assertTrue(np.all(spectrum.values == 0.0))

    def test_smoothing_and_peaks(self) -> None:
        spectrum = Spectrum(48000, 16)
        first = spectrum.update(tone(220.0), 1 / 30)
        self.assertGreater(float(first.max()), 0.0)
        for _ in range(60):
            spectrum.update(tone(220.0), 1 / 30)
        self.assertTrue(np.all(spectrum.peaks >= spectrum.values - 1e-6))
        self.assertGreater(float(spectrum.values.max()), float(first.max()))

        for _ in range(60):
            spectrum.update(np.zeros(4096, dtype=np.float32), 1 / 30)
        self.assertTrue(np.all(spectrum.values < 0.05))

    def test_short_window_is_padded(self) -> None:
        spectrum = Spectrum(44100, 12, window=4096)
        values = spectrum.analyze(tone(440.0, size=100))
        self.assertEqual(values.shape, (12,))
        self.assertTrue(np.all(np.isfinite(values)))

    def test_band_count_fits_width(self) -> None:
        self.assertEqual(bands_for_width(40), 12)
        self.assertGreaterEqual(bands_for_width(119), 30)
        self.assertLessEqual(bands_for_width(400), 48)


if __name__ == "__main__":
    unittest.main()
