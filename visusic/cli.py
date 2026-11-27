"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .app import App
from .discord import load_client_id, save_client_id, valid_client_id
from .effects import effect_names
from .equalizer import CUSTOM_NAME, eq_names
from .library import scan
from .player import AudioError
from .theme import theme_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visusic",
        description="Tiny terminal music visualizer: karaoke lyrics, timeline, spectrum.",
    )
    parser.add_argument(
        "path", nargs="?", default=".",
        help="audio file or folder to scan (default: current folder)",
    )
    parser.add_argument(
        "--fps", type=int, default=30,
        help="render rate, 5-60 (default: 30)",
    )
    parser.add_argument(
        "--volume", type=int, default=75,
        help="start volume in percent, 0-100 (default: 75)",
    )
    parser.add_argument(
        "--theme", choices=theme_names(), default=None,
        help="color theme for this run (default: saved theme, or aurora)",
    )
    parser.add_argument(
        "--eq", choices=eq_names() + [CUSTOM_NAME], default=None,
        help="audio preset for this run (default: saved preset, or flat)",
    )
    parser.add_argument(
        "--effect", choices=effect_names(), default=None,
        help="background effect for this run (default: saved effect, or none)",
    )
    parser.add_argument(
        "--discord-id", default=None, metavar="ID",
        help="Discord Application ID for Rich Presence (saved for later runs)",
    )
    parser.add_argument(
        "--no-discord", action="store_true",
        help="disable Discord Rich Presence for this run",
    )
    parser.add_argument(
        "--version", action="version", version=f"visusic {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if os.name != "nt":
        print("VisuSic Terminal currently supports Windows only.", file=sys.stderr)
        return 1

    target = Path(args.path).expanduser()
    if not target.exists():
        print(f"Path not found: {target}", file=sys.stderr)
        return 2

    tracks = scan(target)
    if not tracks and args.path == ".":
        music = Path.home() / "Music"
        if music.is_dir() and music.resolve() != target.resolve():
            fallback = scan(music)
            if fallback:
                target, tracks = music, fallback

    if not tracks:
        print(f"No audio files found in {target}", file=sys.stderr)
        print("Supported: mp3, flac, wav, ogg, opus, m4a, aac, wma, aiff, "
              "alac, ape, wv, mka", file=sys.stderr)
        return 2

    discord_id = load_client_id()
    if args.discord_id:
        if not valid_client_id(args.discord_id):
            print("Discord Application ID must be a 15-25 digit number.",
                  file=sys.stderr)
            return 2
        if not save_client_id(args.discord_id):
            print("Could not save the Discord ID; using it for this run.",
                  file=sys.stderr)
        discord_id = args.discord_id
    if args.no_discord:
        discord_id = ""

    try:
        app = App(
            tracks,
            fps=max(5, min(60, args.fps)),
            volume=max(0, min(100, args.volume)) / 100.0,
            theme=args.theme,
            eq=args.eq,
            effect=args.effect,
            discord_id=discord_id,
        )
        app.run()
    except AudioError as exc:
        print(f"Audio error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0
