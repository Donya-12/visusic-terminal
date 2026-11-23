"""Application loop: input, playback state and rendering."""

from __future__ import annotations

import time
from pathlib import Path

from . import term
from .keys import KeyReader
from .library import Track
from .lrc import Lyrics, find_for_audio, load as load_lyrics
from .player import AudioError, Player
from .spectrum import Spectrum, bands_for_width
from .ui import Frame, fmt_time, render


class App:
    def __init__(self, tracks: list[Track], fps: int = 30,
                 volume: float = 0.75) -> None:
        if not tracks:
            raise ValueError("playlist is empty")
        self.tracks = tracks
        self.fps = max(5, min(60, fps))
        self.player = Player(volume=volume)
        self.index = 0
        self.track = tracks[0]
        self.duration = 0.0
        self.lyrics: Lyrics | None = None
        self.lyric_offset = 0.0

        self._lyrics_cache: dict[Path, Lyrics | None] = {}
        self._spectrum = Spectrum(self.player.sr, bands_for_width(100))
        self._running = True
        self._status = ""
        self._status_until = 0.0
        self._size = (0, 0)
        self._dt = 1.0 / self.fps

    # ------------------------------------------------------------- playback
    def load(self, index: int, autoplay: bool = True) -> None:
        index %= len(self.tracks)
        track = self.tracks[index]
        self.player.load(track, autoplay=autoplay)

        lyrics = None
        lrc_path = find_for_audio(track.path)
        if lrc_path is not None:
            if lrc_path in self._lyrics_cache:
                lyrics = self._lyrics_cache[lrc_path]
            else:
                try:
                    lyrics = load_lyrics(lrc_path)
                except Exception:
                    lyrics = None
                self._lyrics_cache[lrc_path] = lyrics

        self.index = index
        self.track = track
        self.lyrics = lyrics
        self.duration = self.player.duration
        self.lyric_offset = 0.0
        self._spectrum.clear()
        term.set_title(f"VisuSic Terminal · {track.display}")

    def _load_any(self, index: int, autoplay: bool = True) -> bool:
        last_error = ""
        for step in range(len(self.tracks)):
            candidate = (index + step) % len(self.tracks)
            try:
                self.load(candidate, autoplay=autoplay)
                if last_error:
                    self.toast(f"skipped unreadable track · {last_error}", 3.0)
                return True
            except AudioError as exc:
                last_error = str(exc).splitlines()[0]
        self.toast(f"nothing playable · {last_error}", 5.0)
        return False

    def next_track(self) -> None:
        self._load_any(self.index + 1, autoplay=self.player.playing)

    def previous_track(self) -> None:
        self._load_any(self.index - 1, autoplay=self.player.playing)

    def _advance_if_finished(self) -> None:
        if self.player.finished and self.player.playing:
            if not self._load_any(self.index + 1):
                self.player.pause()

    # ------------------------------------------------------------------ info
    def toast(self, text: str, seconds: float = 1.8) -> None:
        self._status = text
        self._status_until = time.monotonic() + seconds

    def _current_status(self) -> str:
        if self._status and time.monotonic() < self._status_until:
            return self._status
        return ""

    # ----------------------------------------------------------------- input
    def _seek_by(self, delta: float, label: str) -> None:
        target = max(0.0, min(self.duration, self.player.position() + delta))
        self.player.seek(target)
        self.toast(f"{label} · {fmt_time(target)}")

    def handle_key(self, key: str) -> None:
        if key in ("q", "esc", "ctrl-c"):
            self._running = False
        elif key == "space":
            self.player.toggle()
        elif key == "left":
            self._seek_by(-5.0, "−5 s")
        elif key == "right":
            self._seek_by(5.0, "+5 s")
        elif key == "up":
            value = self.player.set_volume(self.player.volume + 0.05)
            self.toast(f"volume {int(round(value * 100))}%")
        elif key == "down":
            value = self.player.set_volume(self.player.volume - 0.05)
            self.toast(f"volume {int(round(value * 100))}%")
        elif key == "n":
            self.next_track()
        elif key == "p":
            self.previous_track()
        elif key == "r" or key == "home":
            self.player.seek(0.0)
            self.toast("restart")
        elif key == "[":
            self.lyric_offset = round(self.lyric_offset - 0.2, 1)
            self.toast(f"lyrics {self.lyric_offset:+.1f} s")
        elif key == "]":
            self.lyric_offset = round(self.lyric_offset + 0.2, 1)
            self.toast(f"lyrics {self.lyric_offset:+.1f} s")

    # ----------------------------------------------------------------- frame
    def _make_frame(self) -> Frame:
        player = self.player
        position = player.position()
        if player.playing:
            bars = self._spectrum.update(player.analysis_window(), self._dt)
            peaks = self._spectrum.peaks.copy()
        else:
            bars = self._spectrum.values.copy()
            peaks = self._spectrum.peaks.copy()

        return Frame(
            title=self.track.title,
            artist=self.track.artist,
            index=self.index,
            total=len(self.tracks),
            position=position,
            duration=self.duration,
            playing=player.playing,
            volume=player.volume,
            bars=bars,
            peaks=peaks,
            lyrics=self.lyrics,
            lyric_time=max(0.0, position + self.lyric_offset),
            lyric_offset=self.lyric_offset,
            status=self._current_status(),
        )

    # ------------------------------------------------------------------- run
    def run(self, key_source=None, max_frames: int | None = None) -> None:
        if not self._load_any(0):
            raise AudioError(self._current_status() or "nothing to play")

        reader = key_source or KeyReader().read
        term.setup()
        first = True
        last_time = time.perf_counter()
        frames = 0
        try:
            while self._running:
                now = time.perf_counter()
                self._dt = max(0.001, min(0.25, now - last_time))
                last_time = now

                for key in reader():
                    self.handle_key(key)
                if not self._running:
                    break

                self._advance_if_finished()

                width, height = term.size()
                if (width, height) != self._size:
                    self._size = (width, height)
                    self._spectrum = Spectrum(
                        self.player.sr, bands_for_width(width)
                    )
                    first = True

                lines = render(self._make_frame(), width, height)
                prefix = "\x1b[2J\x1b[H" if first else "\x1b[H"
                term.write(prefix + "\n".join(lines))
                first = False
                frames += 1

                if max_frames is not None and frames >= max_frames:
                    break

                elapsed = time.perf_counter() - now
                delay = 1.0 / self.fps - elapsed
                if delay > 0:
                    time.sleep(delay)
        finally:
            self.player.close()
            term.teardown()
