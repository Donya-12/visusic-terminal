from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from visusic.lrc import Lyrics, find_for_audio, load, parse

SAMPLE = """[ar:Artist]
[ti:Title]
[offset:250]
[00:01.00]First line
[00:05.25][00:10.00]Second line
[00:12.00]<00:12.00>Hello <00:12.50>big <00:13.00>world
[00:20.00]
"""


class ParseTests(unittest.TestCase):
    def test_basic_lines_and_offset(self) -> None:
        lyrics = parse(SAMPLE)
        self.assertTrue(lyrics)
        self.assertEqual(lyrics.offset, 0.25)
        self.assertEqual(lyrics.tags["ar"], "Artist")
        # Positive offset shifts lyrics earlier by 250 ms.
        self.assertAlmostEqual(lyrics.times[0], 0.75)
        self.assertAlmostEqual(lyrics.times[1], 5.0)
        self.assertEqual(lyrics.lines[0].text, "First line")
        # Empty lines are ignored.
        self.assertEqual(len(lyrics.lines), 4)

    def test_multiple_timestamps_are_split(self) -> None:
        lyrics = parse(SAMPLE)
        second = [line.time for line in lyrics.lines if line.text == "Second line"]
        self.assertEqual(len(second), 2)
        self.assertAlmostEqual(second[0], 5.0)
        self.assertAlmostEqual(second[1], 9.75)

    def test_enhanced_word_timing(self) -> None:
        lyrics = parse(SAMPLE)
        line = next(line for line in lyrics.lines if line.text == "Hello big world")
        index = lyrics.lines.index(line)
        self.assertEqual([w.text.strip() for w in line.words],
                         ["Hello", "big", "world"])
        self.assertAlmostEqual(lyrics.progress(index, 11.0), 0.0)
        self.assertGreater(lyrics.progress(index, 12.55), 0.25)
        self.assertEqual(lyrics.progress(index, 20.0), 1.0)

    def test_index_and_line_progress(self) -> None:
        lyrics = parse("[00:10.00]One\n[00:14.00]Two\n")
        self.assertEqual(lyrics.index_at(9.0), -1)
        self.assertEqual(lyrics.index_at(10.0), 0)
        self.assertEqual(lyrics.index_at(15.0), 1)
        self.assertAlmostEqual(lyrics.progress(0, 12.0), 0.5)

    def test_empty_and_garbage(self) -> None:
        self.assertFalse(parse(""))
        self.assertFalse(parse("just some text\n[ar:Nobody]\n"))
        lyrics = parse("[99:59.99]Long track")
        self.assertAlmostEqual(lyrics.times[0], 5999.99)

    def test_cp1251_file_and_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            audio = folder / "Artist - Song.mp3"
            audio.write_bytes(b"")
            lrc = folder / "artist - song.LRC"
            lrc.write_bytes("[00:01.00]Привет мир\n".encode("cp1251"))

            self.assertEqual(find_for_audio(audio), lrc)
            lyrics = load(lrc)
            self.assertEqual(lyrics.lines[0].text, "Привет мир")

    def test_utf16_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lrc = Path(tmp) / "song.lrc"
            lrc.write_bytes("\ufeff[00:01.00]Привет мир\n".encode("utf-16-le"))
            lyrics = load(lrc)
            self.assertEqual(lyrics.lines[0].text, "Привет мир")

    def test_no_lrc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(find_for_audio(Path(tmp) / "nothing.mp3"))


if __name__ == "__main__":
    unittest.main()
