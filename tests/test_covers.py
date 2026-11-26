from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image

from visusic import metadata
from visusic.covers import _artwork_url, _pick, _score, _skip_reason
from visusic.library import make_track


def result(**overrides) -> dict:
    item = {
        "trackName": "The Winner Takes It All",
        "artistName": "ABBA",
        "collectionName": "ABBA Gold",
        "trackTimeMillis": 295000,
        "artworkUrl100": "https://example.test/100x100bb.jpg",
    }
    item.update(overrides)
    return item


class CoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.track = make_track(Path("ABBA - The Winner Takes It All.mp3"))
        self.info = metadata.TrackInfo(
            artist="ABBA", title="The Winner Takes It All",
            album="ABBA Gold", duration=295.0,
        )

    def test_pick_and_artwork_url(self) -> None:
        wrong = result(artistName="Cher", trackTimeMillis=270000)
        right = result()
        best = _pick([wrong, right], self.track, self.info)
        self.assertIs(best, right)
        self.assertGreater(_score(right, self.track, self.info),
                           _score(wrong, self.track, self.info))
        self.assertEqual(_artwork_url(right),
                         "https://example.test/600x600bb.jpg")

    def test_rejects_wrong_song_and_no_art(self) -> None:
        self.assertIsNone(_pick([result(trackName="Dancing Queen")],
                                self.track, self.info))
        self.assertIsNone(_pick([result(artworkUrl100="")],
                                self.track, self.info))

    def test_cyrillic(self) -> None:
        track = make_track(Path("Кино - Группа крови.mp3"))
        info = metadata.TrackInfo("Кино", "Группа крови", "", 250.0)
        item = result(trackName="Группа крови", artistName="Кино",
                      trackTimeMillis=250000)
        self.assertIsNotNone(_pick([item], track, info))

    def test_skip_existing_sidecar(self) -> None:
        metadata.clear_caches()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Artist - Song.wav"
            sf.write(path, np.zeros((4410, 2), dtype=np.float32), 44100)
            self.assertIsNone(_skip_reason(path, overwrite=False))
            Image.new("RGB", (50, 50), (1, 2, 3)).save(
                path.with_suffix(".jpg"), "JPEG")
            self.assertIsNotNone(_skip_reason(path, overwrite=False))
            self.assertIsNone(_skip_reason(path, overwrite=True))


if __name__ == "__main__":
    unittest.main()
