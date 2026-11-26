from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from visusic.discord import (DEFAULT_CLIENT_ID, build_activity, load_client_id,
                             save_client_id, valid_client_id)


class DiscordTests(unittest.TestCase):
    def test_client_id_validation(self) -> None:
        self.assertTrue(valid_client_id("123456789012345678"))
        self.assertFalse(valid_client_id("123"))
        self.assertFalse(valid_client_id("12345678901234567a"))
        self.assertFalse(valid_client_id(""))

    def test_playing_activity_has_time_range(self) -> None:
        activity = build_activity(
            title="Midnight Drive", artist="Neon Waves",
            album="Terminal Sessions", position=30.0, duration=200.0,
            playing=True, image="cover", now=1000.0,
        )
        self.assertEqual(activity["details"], "♪ Midnight Drive")
        self.assertEqual(activity["state"], "Neon Waves · Terminal Sessions")
        self.assertEqual(activity["start"], 970)
        self.assertEqual(activity["end"], 1170)
        self.assertEqual(activity["large_image"], "cover")
        self.assertFalse(activity["instance"])

    def test_paused_activity_has_no_timer(self) -> None:
        activity = build_activity(
            title="Midnight Drive", artist="Neon Waves", album="",
            position=30.0, duration=200.0, playing=False, now=1000.0,
        )
        self.assertNotIn("start", activity)
        self.assertNotIn("end", activity)
        self.assertTrue(activity["state"].startswith("Paused"))

    def test_save_and_load_client_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            with mock.patch.dict(os.environ, {
                "VISUSIC_CONFIG": str(path),
                "VISUSIC_DISCORD_ID": "",
            }):
                self.assertTrue(valid_client_id(DEFAULT_CLIENT_ID))
                self.assertEqual(load_client_id(), DEFAULT_CLIENT_ID)
                self.assertTrue(save_client_id("123456789012345678"))
                self.assertEqual(load_client_id(), "123456789012345678")
                self.assertFalse(save_client_id("not-an-id"))


if __name__ == "__main__":
    unittest.main()
