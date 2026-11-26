from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from visusic.player import _to_stereo, decode_with_ffmpeg, ffmpeg_exe, resample_linear


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


class FFmpegTests(unittest.TestCase):
    def test_fallback_decodes_m4a(self) -> None:
        executable = ffmpeg_exe()
        if not executable:
            self.skipTest("FFmpeg is not available")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            wav = folder / "tone.wav"
            m4a = folder / "tone.m4a"
            rate = 44100
            t = np.arange(int(rate * 0.5)) / rate
            tone = 0.2 * np.sin(2 * np.pi * 440 * t)
            sf.write(wav, np.stack([tone, tone], axis=1), rate)
            subprocess.run(
                [executable, "-y", "-v", "error", "-i", str(wav),
                 "-c:a", "aac", "-b:a", "128k", str(m4a)],
                check=True,
            )
            data = decode_with_ffmpeg(m4a, 48000)
            self.assertEqual(data.shape[1], 2)
            self.assertAlmostEqual(data.shape[0] / 48000, 0.5, places=1)
            self.assertGreater(float(np.abs(data).max()), 0.01)


if __name__ == "__main__":
    unittest.main()
