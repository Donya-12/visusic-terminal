from __future__ import annotations

import re
import unittest

import numpy as np

from visusic.lrc import parse
from visusic.theme import THEME_LIST, get_theme
from visusic.ui import (Frame, PlaylistRow, PlaylistView, fit_text, render,
                        text_width)

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(line: str) -> str:
    return ANSI.sub("", line)


def frame_with(**kwargs) -> Frame:
    defaults = dict(
        title="Midnight Drive",
        artist="Neon Waves",
        index=2,
        total=9,
        position=42.0,
        duration=200.0,
        playing=True,
        volume=0.8,
        bars=np.linspace(0.05, 1.0, 38, dtype=np.float32),
        peaks=np.linspace(0.1, 1.0, 38, dtype=np.float32),
        lyrics=parse("[00:10.00]First line here\n[00:40.00]Second line\n[00:46.00]Third\n"),
        lyric_time=42.0,
    )
    defaults.update(kwargs)
    return Frame(**defaults)


class LayoutTests(unittest.TestCase):
    def test_sizes_have_exact_width(self) -> None:
        for width, height in ((119, 30), (79, 24), (60, 14), (40, 24), (24, 10)):
            lines = render(frame_with(), width, height)
            self.assertEqual(len(lines), height, (width, height))
            for line in lines:
                self.assertEqual(text_width(plain(line)), width, (width, height, line))

    def test_narrow_heights_use_compact_layout(self) -> None:
        lines = render(frame_with(), 50, 12)
        self.assertEqual(len(lines), 12)
        self.assertIn("Second line", plain("\n".join(lines)))
        self.assertIn("play", plain(lines[-1]))

    def test_tiny_terminal(self) -> None:
        lines = render(frame_with(), 20, 5)
        self.assertEqual(len(lines), 5)
        self.assertIn("too small", plain(" ".join(lines)))

    def test_no_lyrics_hint(self) -> None:
        lines = render(frame_with(lyrics=None), 90, 26)
        text = plain("\n".join(lines))
        self.assertIn("no lyrics", text)

    def test_karaoke_splits_line_into_two_colors(self) -> None:
        lyrics = parse("[00:00.00]0123456789\n[00:05.00]next\n")
        frame = frame_with(
            lyrics=lyrics, lyric_time=2.5, position=2.5,
            bars=np.zeros(20, dtype=np.float32),
            peaks=np.zeros(20, dtype=np.float32),
        )
        lines = render(frame, 80, 24)
        current = lines[24 - 4]
        self.assertIn("\x1b[1m\x1b[38;2;240;246;255m01234", current)
        self.assertIn("\x1b[38;2;98;108;126m56789", current)

    def test_long_lyric_gets_scrolled(self) -> None:
        text = "word " * 60
        lyrics = parse(f"[00:00.00]{text}\n[00:30.00]end\n")
        frame = frame_with(
            lyrics=lyrics, lyric_time=15.0, position=15.0,
            bars=np.zeros(20, dtype=np.float32),
            peaks=np.zeros(20, dtype=np.float32),
        )
        lines = render(frame, 80, 24)
        current = plain(lines[24 - 4])
        self.assertIn("…", current)
        self.assertEqual(text_width(current), 80)

    def test_status_replaces_hints(self) -> None:
        lines = render(frame_with(status="lyrics +0.4 s"), 90, 26)
        footer = plain(lines[-1])
        self.assertIn("lyrics +0.4 s", footer)
        self.assertNotIn("space", footer)

    def test_all_columns_are_used_by_spectrum(self) -> None:
        lines = render(frame_with(playing=True), 100, 26)
        eq_rows = [plain(line) for line in lines[2:24]]
        self.assertTrue(any("█" in row for row in eq_rows))

    def test_paused_is_safe(self) -> None:
        lines = render(frame_with(playing=False), 100, 26)
        self.assertEqual(len(lines), 26)
        self.assertIn("vol 80%", plain(lines[-1]))

    def test_every_theme_renders(self) -> None:
        for theme in THEME_LIST:
            lines = render(frame_with(), 100, 26, theme=theme)
            self.assertEqual(len(lines), 26, theme.name)
            for line in lines:
                self.assertEqual(text_width(plain(line)), 100)
        self.assertEqual(len(render(frame_with(), 80, 24, theme="matrix")), 24)

    def test_theme_menu(self) -> None:
        lines = render(frame_with(), 100, 30, get_theme("synthwave"), menu=1)
        text = plain("\n".join(lines))
        self.assertIn("COLOR THEME", text)
        self.assertIn("Aurora", text)
        self.assertIn("Synthwave", text)
        self.assertIn("Enter", text)
        self.assertIn("Esc", text)
        self.assertEqual(len(lines), 30)
        for line in lines:
            self.assertEqual(text_width(plain(line)), 100)

    def test_theme_menu_scrolls_in_small_terminal(self) -> None:
        for width, height in ((60, 12), (40, 10), (28, 8)):
            lines = render(frame_with(), width, height,
                           get_theme("amber"), menu=5)
            self.assertEqual(len(lines), height)
            for line in lines:
                self.assertEqual(text_width(plain(line)), width)
            self.assertIn("Mono", plain("\n".join(lines)))

    def test_playlist_renders_covers_and_rows(self) -> None:
        theme = get_theme("aurora")
        rows = []
        for i, (artist, title) in enumerate((
            ("Neon Waves", "Midnight Drive"),
            ("The Same Stars", "City Lights"),
            ("8-Bit Bunker", "My Time"),
            ("ABBA", "The Winner Takes It All"),
        )):
            cover = [[theme.eq_color((i + x + y) / 12) for x in range(8)]
                     for y in range(3)]
            rows.append(PlaylistRow(index=i, title=title, artist=artist,
                                    album="Test Album", duration=200.0 + i,
                                    cover=cover, current=i == 0, loaded=True))
        view = PlaylistView(rows=rows, selected=1, current=0)
        lines = render(frame_with(), 100, 30, theme, playlist=view)
        raw = "\n".join(lines)
        text = plain(raw)
        self.assertIn("PLAYLIST", text)
        self.assertIn("City Lights", text)
        self.assertIn("Enter", text)
        self.assertIn("\x1b[48;2;", raw)
        for line in lines:
            self.assertEqual(text_width(plain(line)), 100)

    def test_playlist_in_small_terminal(self) -> None:
        rows = [PlaylistRow(index=i, title=f"Track {i + 1}", artist="Artist")
                for i in range(20)]
        view = PlaylistView(rows=rows, selected=17, current=3)
        for width, height in ((40, 12), (28, 8)):
            lines = render(frame_with(), width, height,
                           get_theme("matrix"), playlist=view)
            self.assertEqual(len(lines), height)
            for line in lines:
                self.assertEqual(text_width(plain(line)), width)


class TextTests(unittest.TestCase):
    def test_fit_text(self) -> None:
        self.assertEqual(fit_text("abcdef", 10), "abcdef")
        self.assertEqual(fit_text("abcdef", 4), "abc…")
        self.assertEqual(fit_text("Привет мир", 6), "Приве…")
        self.assertEqual(fit_text("abc", 0), "")

    def test_widths(self) -> None:
        self.assertEqual(text_width("abc"), 3)
        self.assertEqual(text_width("Привет"), 6)
        self.assertEqual(text_width("日本語"), 6)


if __name__ == "__main__":
    unittest.main()
