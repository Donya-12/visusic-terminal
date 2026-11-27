"""Application loop: input, playback state and rendering."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from . import metadata, term
from .discord import DiscordPresence, load_client_id
from .keys import KeyReader
from .equalizer import (BANDS, CUSTOM_NAME, EQ_LIST, EQPreset, MAX_GAIN,
                        clamp_gains, custom_preset, get_eq)
from .library import Track
from .lrc import Lyrics, find_for_audio, load as load_lyrics
from .player import AudioError, Player
from .smtc import MediaSession
from .spectrum import Spectrum, bands_for_width
from .theme import (THEME_LIST, get_theme, load_setting, load_theme_name,
                    save_setting, save_theme_name)
from .ui import (EQEditorView, Frame, PlaylistRow, PlaylistView, fmt_time,
                 render)


class App:
    def __init__(self, tracks: list[Track], fps: int = 30,
                 volume: float = 0.75, theme: str | None = None,
                 eq: str | None = None,
                 discord_id: str | None = None) -> None:
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
        self.theme = get_theme(theme or load_theme_name())
        saved_eq = eq if eq is not None else load_setting("eq", "flat")
        if not isinstance(saved_eq, str):
            saved_eq = "flat"
        saved_gains = load_setting("eq_gains", ())
        self.custom_gains = clamp_gains(
            saved_gains if isinstance(saved_gains, (list, tuple)) else ()
        )
        self.custom_eq = custom_preset(self.custom_gains)
        self.eq = (self.custom_eq if saved_eq == CUSTOM_NAME
                   else get_eq(saved_eq))
        self.player.set_eq_preset(self.eq)
        self.discord_id = (discord_id if discord_id is not None
                           else load_client_id())
        self.discord: DiscordPresence | None = None
        self._discord_warned = False
        self.menu_index: int | None = None
        self._menu_original: str | None = None
        self.eq_menu_index: int | None = None
        self._eq_original: EQPreset | None = None
        self.eq_edit_band: int | None = None
        self.eq_edit_gains: list[float] = []
        self._eq_edit_original: EQPreset | None = None

        self.playlist_index: int | None = None
        self.playlist_rows: list[PlaylistRow] = []
        self._current_cover: bytes | None = None

        self.smtc: MediaSession | None = None
        self._smtc_error = ""
        self._smtc_warned = False

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
        base = self.tracks[index]
        self.player.load(base, autoplay=autoplay)

        info = metadata.read_info(base.path, base.artist, base.title)
        track = replace(
            base,
            artist=info.artist or base.artist,
            title=info.title or base.title,
            album=info.album,
            duration=info.duration,
        )
        self._current_cover = metadata.cover_bytes(base.path)

        lyrics = None
        lrc_path = find_for_audio(base.path)
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

        if self.playlist_rows:
            for row in self.playlist_rows:
                row.current = row.index == index
            center = (self.playlist_index if self.playlist_index is not None
                      else index)
            self._load_playlist_metadata(center)
        if self.smtc is not None:
            self._sync_media(force=True)
        self._sync_discord(force=True)

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

    # ------------------------------------------------------- windows media
    def _start_media_session(self) -> None:
        try:
            self.smtc = MediaSession()
        except Exception as exc:
            self.smtc = None
            self._smtc_error = str(exc)
            return
        self._sync_media(force=True)

    def _sync_media(self, force: bool = False) -> None:
        if self.smtc is None:
            return
        try:
            self.smtc.update(
                title=self.track.title,
                artist=self.track.artist,
                album=self.track.album,
                position=self.player.position(),
                duration=self.duration,
                playing=self.player.playing,
                cover=self._current_cover,
                force=force,
            )
        except Exception as exc:
            self._smtc_error = str(exc)
            try:
                self.smtc.close()
            except Exception:
                pass
            self.smtc = None
            if not self._smtc_warned:
                self._smtc_warned = True
                self.toast("Windows media controls unavailable", 4.0)

    def _handle_media_command(self, command: str) -> None:
        if command == "play":
            self.player.play()
        elif command == "pause":
            self.player.pause()
        elif command == "next":
            self.next_track()
        elif command == "previous":
            self.previous_track()
        elif command == "stop":
            self.player.pause()
            self.player.seek(0.0)
            self.toast("stopped")
        elif command.startswith("seek:"):
            try:
                target = float(command.split(":", 1)[1])
            except ValueError:
                return
            self.player.seek(target)
            self.toast(f"seek · {fmt_time(target)}")
        self._sync_media(force=True)
        self._sync_discord(force=True)

    # ------------------------------------------------------------- discord
    def _start_discord(self) -> None:
        if not self.discord_id:
            return
        try:
            image = str(load_setting("discord_image", "") or "").strip()
            self.discord = DiscordPresence(self.discord_id, image=image)
        except Exception as exc:
            self.discord = None
            self.toast(f"Discord: {exc}", 3.5)
            return
        self._sync_discord(force=True)

    def _sync_discord(self, force: bool = False) -> None:
        if self.discord is None:
            return
        try:
            self.discord.update(
                title=self.track.title,
                artist=self.track.artist,
                album=self.track.album,
                position=self.player.position(),
                duration=self.duration,
                playing=self.player.playing,
                force=force,
            )
        except Exception as exc:
            try:
                self.discord.close()
            except Exception:
                pass
            self.discord = None
            if not self._discord_warned:
                self._discord_warned = True
                self.toast(f"Discord unavailable · {exc}", 3.5)

    # ------------------------------------------------------------- playlist
    def _ensure_playlist(self) -> None:
        if len(self.playlist_rows) != len(self.tracks):
            self.playlist_rows = [
                PlaylistRow(index=i, title=track.title, artist=track.artist)
                for i, track in enumerate(self.tracks)
            ]
            for row in self.playlist_rows:
                row.current = row.index == self.index

    def _load_playlist_metadata(self, center: int) -> None:
        if not self.playlist_rows:
            return
        center = max(0, min(len(self.playlist_rows) - 1, center))
        start = max(0, center - 6)
        stop = min(len(self.playlist_rows), center + 7)
        for i in range(start, stop):
            row = self.playlist_rows[i]
            if row.loaded:
                continue
            base = self.tracks[i]
            info = metadata.read_info(base.path, base.artist, base.title)
            row.title = info.title or base.title
            row.artist = info.artist or base.artist
            row.album = info.album
            row.duration = info.duration
            row.cover = metadata.cover_mosaic(base.path, 8, 3)
            row.loaded = True

    def _open_playlist(self) -> None:
        self._ensure_playlist()
        self.playlist_index = self.index
        for row in self.playlist_rows:
            row.current = row.index == self.index
        self._load_playlist_metadata(self.index)

    def _close_playlist(self) -> None:
        self.playlist_index = None

    def _move_playlist(self, delta: int) -> None:
        if self.playlist_index is None or not self.playlist_rows:
            return
        index = max(0, min(len(self.playlist_rows) - 1,
                           self.playlist_index + delta))
        self.playlist_index = index
        self._load_playlist_metadata(index)

    def _handle_playlist_key(self, key: str) -> None:
        if key in ("esc", "l", "tab"):
            self._close_playlist()
        elif key in ("q", "ctrl-c"):
            self._running = False
        elif key == "up":
            self._move_playlist(-1)
        elif key == "down":
            self._move_playlist(1)
        elif key == "pageup":
            self._move_playlist(-6)
        elif key == "pagedown":
            self._move_playlist(6)
        elif key == "home":
            self._move_playlist(-len(self.playlist_rows))
        elif key == "end":
            self._move_playlist(len(self.playlist_rows))
        elif key == "enter" and self.playlist_index is not None:
            index = self.playlist_index
            self._close_playlist()
            self._load_any(index, autoplay=True)
            self.toast(f"track · {self.track.display}", 2.0)

    # ----------------------------------------------------------------- input
    def _open_theme_menu(self) -> None:
        self._menu_original = self.theme.name
        names = [theme.name for theme in THEME_LIST]
        self.menu_index = names.index(self.theme.name) if self.theme.name in names else 0

    def _preview_theme(self, index: int) -> None:
        self.menu_index = index % len(THEME_LIST)
        self.theme = THEME_LIST[self.menu_index]

    def _close_theme_menu(self, apply: bool) -> None:
        if apply:
            saved = save_theme_name(self.theme.name)
            suffix = "" if saved else " · config not saved"
            self.toast(f"theme · {self.theme.label}{suffix}", 2.2)
        else:
            if self._menu_original:
                self.theme = get_theme(self._menu_original)
            self.toast(f"theme · {self.theme.label}", 1.2)
        self.menu_index = None
        self._menu_original = None

    def _handle_theme_menu_key(self, key: str) -> None:
        if key == "esc":
            self._close_theme_menu(False)
        elif key == "up":
            self._preview_theme((self.menu_index or 0) - 1)
        elif key == "down":
            self._preview_theme((self.menu_index or 0) + 1)
        elif key == "enter":
            self._close_theme_menu(True)
        elif key in ("q", "ctrl-c"):
            self._running = False
        elif len(key) == 1 and key.isdigit():
            index = int(key) - 1
            if key == "0" and len(THEME_LIST) >= 10:
                index = 9
            if 0 <= index < len(THEME_LIST):
                self._preview_theme(index)
                self._close_theme_menu(True)

    # ---------------------------------------------------------------- audio EQ
    @property
    def eq_presets(self) -> tuple[EQPreset, ...]:
        return EQ_LIST + (self.custom_eq,)

    def _open_eq_menu(self) -> None:
        self._eq_original = self.eq
        names = [preset.name for preset in self.eq_presets]
        self.eq_menu_index = (names.index(self.eq.name)
                              if self.eq.name in names else 0)

    def _preview_eq(self, index: int) -> None:
        presets = self.eq_presets
        self.eq_menu_index = index % len(presets)
        self.eq = presets[self.eq_menu_index]
        self.player.set_eq_preset(self.eq)

    def _close_eq_menu(self, apply: bool) -> None:
        if apply:
            saved = save_setting("eq", self.eq.name)
            if self.eq.name == CUSTOM_NAME:
                saved = (save_setting(
                    "eq_gains", [round(gain, 1) for gain in self.custom_gains]
                ) and saved)
            suffix = "" if saved else " · config not saved"
            self.toast(f"sound · {self.eq.label}{suffix}", 2.0)
        else:
            if self._eq_original is not None:
                self.eq = self._eq_original
            self.player.set_eq_preset(self.eq)
            self.toast(f"sound · {self.eq.label}", 1.2)
        self.eq_menu_index = None
        self._eq_original = None

    def _handle_eq_menu_key(self, key: str) -> None:
        if key == "esc":
            self._close_eq_menu(False)
        elif key == "up":
            self._preview_eq((self.eq_menu_index or 0) - 1)
        elif key == "down":
            self._preview_eq((self.eq_menu_index or 0) + 1)
        elif key == "enter":
            self._close_eq_menu(True)
        elif key in ("q", "ctrl-c"):
            self._running = False
        elif len(key) == 1 and key.isdigit():
            index = int(key) - 1
            if 0 <= index < len(self.eq_presets):
                self._preview_eq(index)
                self._close_eq_menu(True)

    # ---------------------------------------------------------- manual EQ
    def _open_eq_editor(self) -> None:
        self._eq_edit_original = self.eq
        self.eq_edit_gains = [float(gain) for gain in self.eq.gains]
        self.eq_edit_band = 0
        self._preview_eq_editor()

    def _preview_eq_editor(self) -> None:
        if self.eq_edit_band is None:
            return
        self.eq = custom_preset(self.eq_edit_gains)
        self.player.set_eq_preset(self.eq)

    def _set_eq_band(self, value: float) -> None:
        if self.eq_edit_band is None:
            return
        value = max(-MAX_GAIN, min(MAX_GAIN, round(value, 1)))
        self.eq_edit_gains[self.eq_edit_band] = value
        self._preview_eq_editor()

    def _nudge_eq_band(self, delta: float) -> None:
        if self.eq_edit_band is None:
            return
        self._set_eq_band(self.eq_edit_gains[self.eq_edit_band] + delta)

    def _save_eq_editor(self) -> None:
        self.custom_gains = clamp_gains(self.eq_edit_gains)
        self.custom_eq = custom_preset(self.custom_gains)
        self.eq = self.custom_eq
        saved = save_setting("eq", CUSTOM_NAME)
        saved = save_setting("eq_gains",
                             [round(gain, 1) for gain in self.custom_gains]
                             ) and saved
        self.eq_edit_band = None
        self._eq_edit_original = None
        suffix = "" if saved else " · config not saved"
        self.toast(f"custom eq saved{suffix}", 2.2)

    def _close_eq_editor(self, apply: bool) -> None:
        if apply:
            self._save_eq_editor()
            return
        if self._eq_edit_original is not None:
            self.eq = self._eq_edit_original
        self.player.set_eq_preset(self.eq)
        self.eq_edit_band = None
        self._eq_edit_original = None
        self.toast(f"sound · {self.eq.label}", 1.2)

    def _handle_eq_editor_key(self, key: str) -> None:
        if key == "esc":
            self._close_eq_editor(False)
        elif key in ("q", "ctrl-c"):
            self._close_eq_editor(False)
            self._running = False
        elif key == "up":
            self.eq_edit_band = (self.eq_edit_band - 1) % len(BANDS)
        elif key == "down":
            self.eq_edit_band = (self.eq_edit_band + 1) % len(BANDS)
        elif key == "left":
            self._nudge_eq_band(-0.5)
        elif key == "right":
            self._nudge_eq_band(0.5)
        elif key == "pageup":
            self._nudge_eq_band(3.0)
        elif key == "pagedown":
            self._nudge_eq_band(-3.0)
        elif key == "0":
            self._set_eq_band(0.0)
        elif key == "r":
            self.eq_edit_gains = [0.0] * len(BANDS)
            self._preview_eq_editor()
        elif key == "enter":
            self._close_eq_editor(True)

    def _seek_by(self, delta: float, label: str) -> None:
        target = max(0.0, min(self.duration, self.player.position() + delta))
        self.player.seek(target)
        self.toast(f"{label} · {fmt_time(target)}")
        self._sync_discord(force=True)

    def handle_key(self, key: str) -> None:
        if self.eq_edit_band is not None:
            self._handle_eq_editor_key(key)
            return
        if self.menu_index is not None:
            self._handle_theme_menu_key(key)
            return
        if self.playlist_index is not None:
            self._handle_playlist_key(key)
            return
        if self.eq_menu_index is not None:
            self._handle_eq_menu_key(key)
            return

        if key in ("q", "esc", "ctrl-c"):
            self._running = False
        elif key in ("t", "c"):
            self._open_theme_menu()
        elif key in ("l", "tab"):
            self._open_playlist()
        elif key == "e":
            self._open_eq_menu()
        elif key == "m":
            self._open_eq_editor()
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
            self._sync_discord(force=True)
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

        self._start_media_session()
        self._start_discord()
        reader = key_source or KeyReader().read
        term.setup()
        if self._smtc_error:
            self.toast("Windows media controls unavailable", 4.0)
        first = True
        last_time = time.perf_counter()
        frames = 0
        try:
            while self._running:
                now = time.perf_counter()
                self._dt = max(0.001, min(0.25, now - last_time))
                last_time = now

                if self.smtc is not None:
                    for command in self.smtc.poll():
                        self._handle_media_command(command)

                for key in reader():
                    self.handle_key(key)
                if not self._running:
                    break

                self._advance_if_finished()
                self._sync_media()
                self._sync_discord()

                width, height = term.size()
                if (width, height) != self._size:
                    self._size = (width, height)
                    self._spectrum = Spectrum(
                        self.player.sr, bands_for_width(width)
                    )
                    first = True

                playlist = None
                if self.playlist_index is not None:
                    self._ensure_playlist()
                    playlist = PlaylistView(
                        rows=self.playlist_rows,
                        selected=self.playlist_index,
                        current=self.index,
                    )
                eq_editor = None
                if self.eq_edit_band is not None:
                    eq_editor = EQEditorView(
                        gains=list(self.eq_edit_gains),
                        band=self.eq_edit_band,
                    )
                lines = render(self._make_frame(), width, height,
                               self.theme, menu=self.menu_index,
                               playlist=playlist,
                               eq_menu=self.eq_menu_index,
                               eq_presets=self.eq_presets,
                               eq_editor=eq_editor)
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
            if self.discord is not None:
                self.discord.close()
                self.discord = None
            if self.smtc is not None:
                self.smtc.close()
                self.smtc = None
            self.player.close()
            term.teardown()

