from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image
from mutagen.flac import FLAC, Picture

from visusic import metadata


def jpeg_bytes(color: tuple[int, int, int] = (30, 180, 220)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (240, 180), color).save(buffer, "JPEG")
    return buffer.getvalue()


class MetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        metadata.clear_caches()

    def test_flac_tags_and_embedded_cover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Artist - Song.flac"
            sf.write(path, np.zeros((4410, 2), dtype=np.float32), 44100)
            audio = FLAC(path)
            audio["artist"] = "Test Artist"
            audio["title"] = "Test Song"
            audio["album"] = "Test Album"
            picture = Picture()
            picture.data = jpeg_bytes()
            picture.mime = "image/jpeg"
            picture.type = 3
            audio.add_picture(picture)
            audio.save()

            metadata.clear_caches()
            info = metadata.read_info(path, "Fallback", "Song")
            self.assertEqual(info.artist, "Test Artist")
            self.assertEqual(info.title, "Test Song")
            self.assertEqual(info.album, "Test Album")
            self.assertAlmostEqual(info.duration or 0, 0.1, places=1)
            self.assertEqual(metadata.cover_bytes(path), picture.data)

            mosaic = metadata.cover_mosaic(path, 8, 3)
            self.assertIsNotNone(mosaic)
            assert mosaic is not None
            self.assertEqual(len(mosaic), 3)
            self.assertEqual(len(mosaic[0]), 8)
            self.assertEqual(len(mosaic[0][0]), 3)

    def test_fallback_and_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Artist - Song.wav"
            sf.write(path, np.zeros((4410, 2), dtype=np.float32), 44100)
            info = metadata.read_info(path, "Fallback Artist", "Fallback Title")
            self.assertEqual(info.artist, "Fallback Artist")
            self.assertEqual(info.title, "Fallback Title")
            self.assertIsNone(metadata.cover_bytes(path))

            cover = path.with_suffix(".jpg")
            Image.new("RGB", (100, 100), (10, 40, 90)).save(cover, "JPEG")
            metadata.clear_caches()
            self.assertEqual(metadata.sidecar_cover(path), cover)
            self.assertIsNotNone(metadata.cover_bytes(path))
            self.assertIsNotNone(metadata.cover_mosaic(path))
            self.assertTrue(metadata.has_cover(path))

    def test_missing_cover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nothing.ogg"
            path.write_bytes(b"")
            self.assertIsNone(metadata.cover_bytes(path))
            self.assertIsNone(metadata.cover_mosaic(path))


if __name__ == "__main__":
    unittest.main()
