from __future__ import annotations

import unittest

import numpy as np

from visusic.player import _to_stereo, resample_linear


class StereoTests(unittest.TestCase):
    def test_mono_is_duplicated(self) -> None:
        mono = np.arange(6, dtype=np.float32)[:, None]
        stereo = _to_stereo(mono)
        self.assertEqual(stereo.shape, (6, 2))
        np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])

    def test_multichannel_is_trimmed(self) -> None:
        data = np.arange(24, dtype=np.float32).reshape(6, 4)
        self.assertEqual(_to_stereo(data).shape, (6, 2))


class ResampleTests(unittest.TestCase):
    def test_identity(self) -> None:
        data = np.random.default_rng(1).random((1000, 2), dtype=np.float32)
        self.assertIs(resample_linear(data, 44100, 44100), data)

    def test_rates(self) -> None:
        up = resample_linear(np.zeros((44100, 2), dtype=np.float32), 44100, 48000)
        down = resample_linear(np.zeros((48000, 2), dtype=np.float32), 48000, 44100)
        self.assertEqual(up.shape, (48000, 2))
        self.assertEqual(down.shape, (44100, 2))

    def test_constant_signal_stays_constant(self) -> None:
        data = np.full((4800, 2), 0.25, dtype=np.float32)
        result = resample_linear(data, 44100, 48000)
        self.assertTrue(np.allclose(result, 0.25, atol=1e-6))


if __name__ == "__main__":
    unittest.main()
