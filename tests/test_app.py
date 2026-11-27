from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from visusic.app import App
from visusic.equalizer import BANDS, EQ_LIST, PRESETS, MAX_GAIN
from visusic.library import Track


class FakePlayer:
    sr = 48000

    def __init__(self, volume: float = 0.75) -> None:
        self.volume = volume
        self.preset = None

    def set_eq_preset(self, preset) -> None:
        self.preset = preset

    def close(self) -> None:
        pass


class AppEqTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "config.json"
        env = mock.patch.dict(os.environ, {
            "VISUSIC_CONFIG": str(self.config),
            "VISUSIC_DISCORD_ID": "",
        })
        env.start()
        self.addCleanup(env.stop)
        player = mock.patch("visusic.app.Player", FakePlayer)
        player.start()
        self.addCleanup(player.stop)

    def make_app(self, eq: str | None = None) -> App:
        track = Track(path=Path("song.mp3"), artist="Artist", title="Title")
        return App([track], eq=eq, discord_id="")

    def test_editor_starts_from_active_gains(self) -> None:
        app = self.make_app(eq="bass")
        app.handle_key("m")
        self.assertEqual(app.eq_edit_band, 0)
        self.assertEqual(tuple(app.eq_edit_gains), PRESETS["bass"].gains)
        self.assertEqual(app.player.preset.gains, PRESETS["bass"].gains)

    def test_editor_saves_custom_preset(self) -> None:
        app = self.make_app(eq="flat")
        app.handle_key("m")
        app.handle_key("down")
        app.handle_key("right")
        app.handle_key("right")
        app.handle_key("pageup")
        app.handle_key("enter")

        self.assertIsNone(app.eq_edit_band)
        self.assertEqual(app.eq.name, "custom")
        self.assertEqual(app.eq.gains[1], 4.0)
        self.assertEqual(app.eq.gains[0], 0.0)

        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(saved["eq"], "custom")
        self.assertEqual(len(saved["eq_gains"]), len(BANDS))
        self.assertEqual(saved["eq_gains"][1], 4.0)

    def test_editor_escape_restores_previous_preset(self) -> None:
        app = self.make_app(eq="rock")
        app.handle_key("m")
        app.handle_key("down")
        app.handle_key("right")
        self.assertEqual(app.eq.name, "custom")
        app.handle_key("esc")
        self.assertEqual(app.eq.name, "rock")
        self.assertIsNone(app.eq_edit_band)
        self.assertEqual(app.player.preset.name, "rock")

    def test_editor_clamps_and_resets(self) -> None:
        app = self.make_app(eq="flat")
        app.handle_key("m")
        for _ in range(40):
            app.handle_key("right")
        self.assertEqual(app.eq_edit_gains[0], MAX_GAIN)
        for _ in range(80):
            app.handle_key("left")
        self.assertEqual(app.eq_edit_gains[0], -MAX_GAIN)
        app.handle_key("r")
        self.assertEqual(app.eq_edit_gains, [0.0] * len(BANDS))
        app.handle_key("esc")

    def test_custom_is_loaded_from_config(self) -> None:
        gains = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        self.config.write_text(json.dumps({
            "eq": "custom",
            "eq_gains": gains,
        }), encoding="utf-8")
        app = self.make_app()
        self.assertEqual(app.eq.name, "custom")
        self.assertEqual(app.eq.gains, tuple(gains))
        self.assertEqual(len(app.eq_presets), len(EQ_LIST) + 1)
        self.assertEqual(app.eq_presets[-1].label, "Custom")
        self.assertEqual(app.player.preset.gains, tuple(gains))

    def test_custom_row_in_preset_menu(self) -> None:
        app = self.make_app(eq="flat")
        app.handle_key("e")
        names = [preset.name for preset in app.eq_presets]
        self.assertEqual(app.eq_menu_index, names.index("flat"))
        app.handle_key("up")
        self.assertEqual(app.eq.name, "custom")
        app.handle_key("enter")
        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(saved["eq"], "custom")


if __name__ == "__main__":
    unittest.main()
