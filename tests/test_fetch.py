from __future__ import annotations

import unittest
from pathlib import Path

from visusic.fetch import _normalize, _pick, _score
from visusic.library import make_track


def result(**overrides) -> dict:
    item = {
        "trackName": "The Winner Takes It All",
        "artistName": "ABBA",
        "duration": 295.0,
        "syncedLyrics": "[00:01.00]hello\n",
        "instrumental": False,
    }
    item.update(overrides)
    return item


class FetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.track = make_track(Path("ABBA - The Winner Takes It All.mp3"))

    def test_normalize(self) -> None:
        self.assertEqual(_normalize("AC/DC — Hell's Bells"),
                         "ac dc hell s bells")
        self.assertEqual(_normalize("  Привет, мир! "), "привет мир")

    def test_exact_match_wins(self) -> None:
        wrong = result(duration=180.0)
        right = result()
        best = _pick([wrong, right], self.track, 295.0)
        self.assertIs(best, right)
        self.assertGreater(_score(right, self.track, 295.0),
                           _score(wrong, self.track, 295.0))

    def test_plain_or_instrumental_is_ignored(self) -> None:
        self.assertIsNone(_pick([result(syncedLyrics=None)],
                                self.track, 295.0))
        self.assertIsNone(_pick([result(instrumental=True)],
                                self.track, 295.0))

    def test_wrong_song_is_rejected(self) -> None:
        other = result(trackName="Dancing Queen", artistName="ABBA")
        self.assertIsNone(_pick([other], self.track, 295.0))

    def test_cyrillic_titles(self) -> None:
        track = make_track(Path("Кино - Группа крови.mp3"))
        item = result(trackName="Группа крови", artistName="Кино",
                      duration=250.0)
        self.assertIsNotNone(_pick([item], track, 250.0))


if __name__ == "__main__":
    unittest.main()
