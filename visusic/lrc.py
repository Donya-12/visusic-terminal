"""Minimal LRC lyrics parser with karaoke-friendly timing.

Supports plain LRC lines, multiple timestamps per line, the global
``[offset:...]`` tag and enhanced (word-level) timestamps such as
``<00:12.30>word``.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path

_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_WORD = re.compile(r"<(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)>([^<]*)")
_META = re.compile(r"^\[([A-Za-z]+):(.*)\]$")
_ENCODINGS = ("utf-8-sig", "cp1251", "latin-1")

_MIN_LINE_SECONDS = 0.9
_MAX_LINE_SECONDS = 7.0


def _timestamp(minutes: str, seconds: str) -> float:
    return int(minutes) * 60.0 + float(seconds.replace(":", "."))


@dataclass(frozen=True)
class Word:
    time: float
    text: str


@dataclass
class LyricLine:
    time: float
    text: str
    words: tuple[Word, ...] = ()


@dataclass
class Lyrics:
    lines: list[LyricLine] = field(default_factory=list)
    offset: float = 0.0
    tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._resort()

    def _resort(self) -> None:
        self.lines.sort(key=lambda line: line.time)
        self._times = [line.time for line in self.lines]

    def __bool__(self) -> bool:
        return bool(self.lines)

    @property
    def times(self) -> list[float]:
        return self._times

    def index_at(self, t: float) -> int:
        """Index of the line that is currently being sung, or -1."""
        return bisect.bisect_right(self._times, t) - 1

    def next_time(self, index: int) -> float | None:
        if 0 <= index + 1 < len(self.lines):
            return self.lines[index + 1].time
        return None

    def progress(self, index: int, t: float) -> float:
        """How much of the line is already sung, from 0.0 to 1.0."""
        if not 0 <= index < len(self.lines):
            return 0.0
        line = self.lines[index]
        if t <= line.time:
            return 0.0

        if line.words:
            return self._word_progress(line, t)

        end = self.next_time(index)
        duration = _MAX_LINE_SECONDS if end is None else end - line.time
        duration = min(max(duration, _MIN_LINE_SECONDS), _MAX_LINE_SECONDS)
        return min(1.0, (t - line.time) / duration)

    @staticmethod
    def _word_progress(line: LyricLine, t: float) -> float:
        total = len(line.text)
        if total == 0:
            return 1.0
        played = 0.0
        position = 0
        for i, word in enumerate(line.words):
            length = len(word.text)
            if t >= word.time:
                if i + 1 < len(line.words):
                    span = max(0.05, line.words[i + 1].time - word.time)
                    part = min(1.0, (t - word.time) / span)
                else:
                    part = min(1.0, (t - word.time) / 0.4)
                played = position + part * length
            position += length
        return min(1.0, played / total)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse(text: str) -> Lyrics:
    lyrics = Lyrics()
    pending: list[tuple[float, str, tuple[Word, ...]]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        stamps = [_timestamp(m, s) for m, s in _TIME.findall(line)]
        body = _TIME.sub("", line).strip()

        if stamps:
            words = tuple(
                Word(_timestamp(m, s), word)
                for m, s, word in _WORD.findall(body)
            )
            display = _WORD.sub(r"\3", body).strip()
            if not display:
                continue
            for stamp in stamps:
                pending.append((stamp, display, words))
            continue

        meta = _META.match(line)
        if meta:
            key, value = meta.group(1).lower(), meta.group(2).strip()
            lyrics.tags[key] = value
            if key == "offset":
                try:
                    # LRC convention: a positive offset shows the lyrics earlier.
                    lyrics.offset = int(float(value)) / 1000.0
                except ValueError:
                    pass

    shift = -lyrics.offset
    for stamp, display, words in pending:
        shifted_words = tuple(Word(w.time + shift, w.text) for w in words)
        lyrics.lines.append(
            LyricLine(stamp + shift, display, shifted_words)
        )

    lyrics._resort()
    return lyrics


def load(path: Path | str) -> Lyrics:
    return parse(_read_text(Path(path)))


def find_for_audio(audio_path: Path) -> Path | None:
    """Find a sidecar .lrc file, tolerating different casing."""
    direct = audio_path.with_suffix(".lrc")
    if direct.is_file():
        return direct
    upper = audio_path.with_suffix(".LRC")
    if upper.is_file():
        return upper

    stem = audio_path.stem.lower()
    try:
        siblings = audio_path.parent.iterdir()
    except OSError:
        return None
    for candidate in siblings:
        if candidate.suffix.lower() == ".lrc" and candidate.stem.lower() == stem:
            return candidate
    return None
