from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from visusic.library import make_track, parse_name, scan


class NamingTests(unittest.TestCase):
    def test_artist_title(self) -> None:
        self.assertEqual(
            parse_name(Path("ABBA - The Winner Takes It All.mp3")),
            ("ABBA", "The Winner Takes It All"),
        )

    def test_track_number_and_underscores(self) -> None:
        self.assertEqual(
            parse_name(Path("07 - Daft_Punk - Aerodynamic.flac")),
            ("Daft Punk", "Aerodynamic"),
        )
        self.assertEqual(
            parse_name(Path("01. Intro.mp3")),
            ("", "Intro"),
        )

    def test_title_only(self) -> None:
        artist, title = parse_name(Path("Island Song.mp3"))
        self.assertEqual(artist, "")
        self.assertEqual(title, "Island Song")

    def test_display(self) -> None:
        track = make_track(Path("Neon Waves - Midnight Drive.mp3"))
        self.assertEqual(track.display, "Neon Waves — Midnight Drive")


class ScanTests(unittest.TestCase):
    def test_recursive_natural_sort_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "album").mkdir()
            (root / ".hidden").mkdir()
            for name in ("10 - Ten.mp3", "2 - Two.mp3", "1 - One.mp3",
                         "notes.txt", "cover.jpg"):
                (root / "album" / name).write_bytes(b"")
            (root / ".hidden" / "secret.mp3").write_bytes(b"")
            (root / "root.wav").write_bytes(b"")

            tracks = scan(root)
            names = [track.path.name for track in tracks]
            self.assertEqual(names, ["1 - One.mp3", "2 - Two.mp3",
                                     "10 - Ten.mp3", "root.wav"])

    def test_single_file_and_unknown_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "Artist - Song.mp3"
            audio.write_bytes(b"")
            self.assertEqual(len(scan(audio)), 1)
            self.assertEqual(scan(Path(tmp) / "missing.mp3"), [])


if __name__ == "__main__":
    unittest.main()
