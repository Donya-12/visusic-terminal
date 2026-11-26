"""Track discovery and filename-based metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".ogg", ".oga", ".opus", ".aiff", ".aif",
    ".m4a", ".m4b", ".aac", ".wma", ".alac", ".ape", ".wv", ".mka",
}
_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "$RECYCLE.BIN",
              "System Volume Information"}
_TRACK_NUMBER = re.compile(r"^\s*\d{1,2}\s*[.\-_)]\s+")


@dataclass(frozen=True)
class Track:
    path: Path
    artist: str
    title: str
    album: str = ""
    duration: float | None = None

    @property
    def display(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title


def _natural_key(path: Path) -> list[tuple[int, object]]:
    parts = re.split(r"(\d+)", str(path).lower())
    return [(0, int(part)) if part.isdigit() else (1, part) for part in parts]


def parse_name(path: Path) -> tuple[str, str]:
    stem = path.stem.replace("_", " ").strip()
    stem = _TRACK_NUMBER.sub("", stem).strip()

    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        artist, title = artist.strip(), title.strip()
        if artist and title:
            return artist, title
    return "", stem


def make_track(path: Path) -> Track:
    artist, title = parse_name(path)
    return Track(path=path, artist=artist, title=title or path.stem)


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def scan(target: Path) -> list[Track]:
    target = target.expanduser()
    if target.is_file():
        return [make_track(target)] if is_audio(target) else []

    files: list[Path] = []
    for path in target.rglob("*"):
        if not path.is_file() or not is_audio(path):
            continue
        if any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts):
            continue
        files.append(path)

    files.sort(key=_natural_key)
    return [make_track(path) for path in files]
