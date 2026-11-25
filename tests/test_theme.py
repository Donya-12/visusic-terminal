from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from visusic.theme import (
    DEFAULT_THEME,
    THEME_LIST,
    THEMES,
    get_theme,
    load_theme_name,
    mix,
    save_theme_name,
)


class ThemeTests(unittest.TestCase):
    def test_default_and_unknown(self) -> None:
        self.assertEqual(get_theme(None).name, DEFAULT_THEME)
        self.assertEqual(get_theme("no-such-theme").name, DEFAULT_THEME)
        self.assertIn("aurora", THEMES)

    def test_presets_are_valid(self) -> None:
        self.assertGreaterEqual(len(THEME_LIST), 5)
        self.assertEqual(len({theme.name for theme in THEME_LIST}),
                         len(THEME_LIST))
        for theme in THEME_LIST:
            self.assertEqual(theme.name, theme.name.lower())
            self.assertTrue(theme.label)
            for field in ("accent", "accent_dim", "white", "text", "dim",
                          "dim2", "warn", "lyric_todo", "lyric_context"):
                color = getattr(theme, field)
                self.assertEqual(len(color), 3)
                self.assertTrue(all(0 <= channel <= 255 for channel in color),
                                (theme.name, field, color))
            stops = theme.eq_stops
            self.assertGreaterEqual(len(stops), 3)
            self.assertEqual(stops[0][0], 0.0)
            self.assertEqual(stops[-1][0], 1.0)
            self.assertEqual([stop[0] for stop in stops],
                             sorted(stop[0] for stop in stops))

    def test_gradient(self) -> None:
        theme = get_theme("aurora")
        self.assertEqual(theme.eq_color(0.0), theme.eq_stops[0][1])
        self.assertEqual(theme.eq_color(1.0), theme.eq_stops[-1][1])
        middle = theme.eq_color(0.5)
        self.assertTrue(all(0 <= channel <= 255 for channel in middle))
        self.assertEqual(mix((0, 0, 0), (10, 20, 30), 0.5), (5, 10, 15))
        self.assertEqual(mix((0, 0, 0), (10, 20, 30), 2.0), (10, 20, 30))

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.json"
            self.assertEqual(load_theme_name(path), DEFAULT_THEME)
            self.assertTrue(save_theme_name("matrix", path))
            self.assertEqual(load_theme_name(path), "matrix")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"theme": "matrix"})

    def test_invalid_config_and_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_theme_name(path), DEFAULT_THEME)
            path.write_text('{"theme": "nope"}', encoding="utf-8")
            self.assertEqual(load_theme_name(path), DEFAULT_THEME)
            self.assertFalse(save_theme_name("nope", path))
            self.assertEqual(load_theme_name(path), DEFAULT_THEME)


if __name__ == "__main__":
    unittest.main()
