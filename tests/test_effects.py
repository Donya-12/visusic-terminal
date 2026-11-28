from __future__ import annotations

import re
import unittest

import numpy as np

from visusic.effects import (EFFECT_LIST, Background, effect_names,
                             get_effect)
from visusic.theme import get_theme
from visusic.ui import Canvas, text_width

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def draw_text(background: Background, width: int = 80,
              height: int = 24) -> str:
    canvas = Canvas(width, height)
    background.draw(canvas, get_theme("aurora"))
    return "\n".join(canvas.to_lines())


def cells(text: str) -> int:
    return sum(1 for char in ANSI.sub("", text) if char not in " \n")


class EffectMetaTests(unittest.TestCase):
    def test_effect_names_and_reactive_flags(self) -> None:
        names = effect_names()
        self.assertIn("none", names)
        self.assertIn("snow", names)
        self.assertIn("waves", names)
        self.assertEqual(names, [effect.name for effect in EFFECT_LIST])

        self.assertFalse(get_effect("snow").reactive)
        self.assertFalse(get_effect("rain").reactive)
        self.assertFalse(get_effect("none").reactive)
        self.assertTrue(get_effect("waves").reactive)
        self.assertTrue(get_effect("stars").reactive)
        self.assertTrue(get_effect("bubbles").reactive)

    def test_unknown_effect_falls_back(self) -> None:
        self.assertEqual(get_effect("nope").name, "none")
        self.assertEqual(get_effect(None).name, "none")


class BackgroundTests(unittest.TestCase):
    def run_effect(self, name: str, bars) -> Background:
        background = Background(name)
        for _ in range(40):
            background.update(1 / 30, 80, 24, bars, True)
        return background

    def test_none_draws_nothing(self) -> None:
        background = self.run_effect("none", np.ones(40))
        self.assertEqual(cells(draw_text(background)), 0)

    def test_every_effect_draws_something(self) -> None:
        bars = np.linspace(0.1, 1.0, 40, dtype=np.float32)
        for effect in EFFECT_LIST:
            if effect.name == "none":
                continue
            background = self.run_effect(effect.name, bars)
            self.assertGreater(cells(draw_text(background)), 0, effect.name)

    def test_snow_and_rain_ignore_music(self) -> None:
        for name in ("snow", "rain"):
            quiet = self.run_effect(name, np.zeros(40, dtype=np.float32))
            loud = self.run_effect(name, np.ones(40, dtype=np.float32))
            self.assertEqual(draw_text(quiet), draw_text(loud), name)

    def test_waves_and_stars_follow_music(self) -> None:
        for name in ("waves", "stars", "bubbles"):
            quiet = self.run_effect(name, np.zeros(40, dtype=np.float32))
            loud = self.run_effect(name, np.ones(40, dtype=np.float32))
            self.assertNotEqual(draw_text(quiet), draw_text(loud), name)

    def test_resize_respawns_without_errors(self) -> None:
        background = Background("snow")
        background.update(1 / 30, 60, 20, np.ones(30), True)
        background.update(1 / 30, 120, 40, np.ones(60), True)
        canvas = Canvas(120, 40)
        background.draw(canvas, get_theme("matrix"))
        text = "\n".join(canvas.to_lines())
        self.assertGreater(cells(text), 0)
        for line in text.splitlines():
            self.assertEqual(text_width(ANSI.sub("", line)), 120)

    def test_set_effect_resets_particles(self) -> None:
        background = Background("snow")
        background.update(1 / 30, 80, 24, np.ones(40), True)
        self.assertEqual(background.name, "snow")
        background.set_effect("waves")
        self.assertEqual(background.name, "waves")
        self.assertTrue(background.reactive)
        background.set_effect("nope")
        self.assertEqual(background.name, "none")


    def test_snow_uses_plain_symbols(self) -> None:
        background = self.run_effect("snow", np.ones(40))
        text = draw_text(background)
        self.assertNotIn("❄", text)
        self.assertTrue(any(char in text for char in "*·+"))


if __name__ == "__main__":
    unittest.main()
