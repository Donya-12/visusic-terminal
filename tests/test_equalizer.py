from __future__ import annotations

import unittest

import numpy as np

from visusic.equalizer import (BANDS, CUSTOM_NAME, EQ_LIST, MAX_GAIN, PRESETS,
                               TAPS, clamp_gains, custom_preset, design_taps,
                               eq_names, get_eq)


class EqualizerTests(unittest.TestCase):
    def test_presets_are_valid(self) -> None:
        self.assertGreaterEqual(len(EQ_LIST), 5)
        self.assertEqual(len(eq_names()), len(EQ_LIST))
        for preset in EQ_LIST:
            self.assertEqual(len(preset.gains), len(BANDS))
            self.assertTrue(all(-12 <= gain <= 12 for gain in preset.gains))
            self.assertTrue(preset.label)
            self.assertTrue(preset.description)

    def test_flat_is_bypass_and_unknown_falls_back(self) -> None:
        self.assertIsNone(design_taps(PRESETS["flat"], 48000))
        self.assertEqual(get_eq("nope").name, "flat")
        self.assertEqual(get_eq("bass").name, "bass")

    def test_design_matches_target(self) -> None:
        samplerate = 48000
        for name in ("bass", "vocal", "rock", "electronic", "night"):
            preset = PRESETS[name]
            taps = design_taps(preset, samplerate)
            self.assertIsNotNone(taps)
            assert taps is not None
            self.assertEqual(len(taps), TAPS)
            self.assertTrue(np.all(np.isfinite(taps)))

            size = 16384
            response = np.fft.rfft(taps, size)
            freqs = np.fft.rfftfreq(size, 1 / samplerate)
            got = 20 * np.log10(np.abs(response) + 1e-9)
            target = np.array(preset.gains) + preset.preamp
            for frequency, expected in zip(BANDS, target):
                index = int(np.argmin(np.abs(freqs - frequency)))
                self.assertLess(abs(float(got[index]) - float(expected)), 2.5,
                                (name, frequency, got[index], expected))

    def test_clamp_gains_pads_and_clamps(self) -> None:
        self.assertEqual(clamp_gains([]), (0.0,) * len(BANDS))
        self.assertEqual(len(clamp_gains([1, 2])), len(BANDS))
        values = clamp_gains([99, -99, "3.14", None, -0.04, 0.06])
        self.assertEqual(values[:6], (MAX_GAIN, -MAX_GAIN, 3.1, 0.0, 0.0, 0.1))
        self.assertTrue(all(isinstance(value, float) for value in values))

    def test_custom_preset_applies_headroom(self) -> None:
        preset = custom_preset([6, 4, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(preset.name, CUSTOM_NAME)
        self.assertEqual(preset.label, "Custom")
        self.assertEqual(preset.gains, (6, 4, 0, 0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(preset.preamp, -3.0)

        quiet = custom_preset([-6, -3, 0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(quiet.preamp, 0.0)

        taps = design_taps(preset, 48000)
        self.assertIsNotNone(taps)
        self.assertIsNone(design_taps(custom_preset([]), 48000))


if __name__ == "__main__":
    unittest.main()
