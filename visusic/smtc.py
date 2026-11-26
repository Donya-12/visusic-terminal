"""Windows System Media Transport Controls bridge.

Windows sees a normal media session: title/artist/album, cover art, play/pause,
next/previous and the timeline.  A muted looping silent source keeps the session
alive while VisuSic plays audio through sounddevice.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import queue
import tempfile
import threading
import wave
from ctypes import wintypes
from datetime import timedelta
from pathlib import Path

try:
    from winrt.windows.foundation import Uri
    from winrt.windows.media import (
        MediaPlaybackStatus,
        MediaPlaybackType,
        SystemMediaTransportControlsButton,
        SystemMediaTransportControlsTimelineProperties,
    )
    from winrt.windows.media.core import MediaSource
    from winrt.windows.media.playback import MediaPlayer
    from winrt.windows.storage import StorageFile
    from winrt.windows.storage.streams import RandomAccessStreamReference

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - depends on Windows packages
    _IMPORT_ERROR = exc


class MediaSessionError(RuntimeError):
    pass


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def _pump_messages() -> None:
    """Let WinRT deliver media-key events while the render loop is running."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        message = _MSG()
        while user32.PeekMessageW(ctypes.byref(message), 0, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
    except Exception:
        pass


def _write_silence(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size > 0:
        return
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\x00" * 44100 * 4)


def _run_async(coro):
    """Run a WinRT coroutine, even if the caller already has an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


class MediaSession:
    def __init__(self) -> None:
        if _IMPORT_ERROR is not None:
            raise MediaSessionError(
                f"WinRT media APIs are unavailable: {_IMPORT_ERROR}"
            )

        self._queue: queue.Queue[str] = queue.Queue()
        self._temp = Path(tempfile.gettempdir()) / "visusic-terminal"
        self._temp.mkdir(parents=True, exist_ok=True)
        silent = self._temp / "silence.wav"
        _write_silence(silent)

        self._player = MediaPlayer()
        try:
            self._player.command_manager.is_enabled = False
        except Exception:
            pass
        self._player.volume = 0.0
        self._player.is_muted = True
        self._player.is_looping_enabled = True
        self._player.source = MediaSource.create_from_uri(Uri(silent.as_uri()))
        self._player.play()

        self._smtc = self._player.system_media_transport_controls
        self._smtc.is_enabled = True
        self._smtc.is_play_enabled = True
        self._smtc.is_pause_enabled = False
        self._smtc.is_next_enabled = True
        self._smtc.is_previous_enabled = True
        self._smtc.is_stop_enabled = False
        self._smtc.display_updater.type = MediaPlaybackType.MUSIC
        self._smtc.add_button_pressed(self._on_button)
        self._smtc.add_playback_position_change_requested(self._on_seek)

        self._meta_key: tuple[str, str, str, str] | None = None
        self._cover_key: str | None = None
        self._thumb_ref = None
        self._playing: bool | None = None
        self._duration = 0.0
        self._position = 0.0
        self._closed = False

    # ----------------------------------------------------------------- events
    def _on_button(self, _sender, args) -> None:
        try:
            button = int(args.button)
        except Exception:
            return
        mapping = {
            int(SystemMediaTransportControlsButton.PLAY): "play",
            int(SystemMediaTransportControlsButton.PAUSE): "pause",
            int(SystemMediaTransportControlsButton.STOP): "stop",
            int(SystemMediaTransportControlsButton.NEXT): "next",
            int(SystemMediaTransportControlsButton.PREVIOUS): "previous",
        }
        command = mapping.get(button)
        if command:
            self._queue.put(command)

    def _on_seek(self, _sender, args) -> None:
        value = args.requested_playback_position
        try:
            seconds = value.total_seconds()
        except AttributeError:
            seconds = float(value) / 10_000_000.0
        self._queue.put(f"seek:{seconds:.3f}")

    def poll(self) -> list[str]:
        _pump_messages()
        commands: list[str] = []
        while True:
            try:
                commands.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return commands

    # --------------------------------------------------------------- artwork
    def _thumb_from_bytes(self, data: bytes):
        digest = hashlib.sha1(data).hexdigest()[:12]
        if self._cover_key == digest and self._thumb_ref is not None:
            return self._thumb_ref
        target = self._temp / f"cover-{digest}.jpg"
        if not target.is_file():
            try:
                from io import BytesIO

                from PIL import Image

                image = Image.open(BytesIO(data)).convert("RGB")
                width, height = image.size
                side = min(width, height)
                left = (width - side) // 2
                top = (height - side) // 2
                image = image.crop((left, top, left + side, top + side))
                image = image.resize((600, 600), Image.Resampling.LANCZOS)
                image.save(target, "JPEG", quality=92, optimize=True)
            except Exception:
                target.write_bytes(data)

        async def make():
            file = await StorageFile.get_file_from_path_async(str(target))
            return RandomAccessStreamReference.create_from_file(file)

        reference = _run_async(make())
        self._cover_key = digest
        self._thumb_ref = reference
        return reference

    def _apply_cover(self, cover: bytes | None) -> None:
        try:
            if cover:
                reference = self._thumb_from_bytes(cover)
            else:
                reference = None
            self._smtc.display_updater.thumbnail = reference
        except Exception:
            pass

    # ---------------------------------------------------------------- update
    def update(self, *, title: str, artist: str, album: str,
               position: float, duration: float, playing: bool,
               cover: bytes | None = None, force: bool = False) -> None:
        if self._closed:
            return
        title = title.strip() or "VisuSic Terminal"
        artist = artist.strip()
        album = album.strip()
        cover_key = hashlib.sha1(cover).hexdigest() if cover else ""
        meta_key = (title, artist, album, cover_key)
        if force or meta_key != self._meta_key:
            updater = self._smtc.display_updater
            updater.music_properties.title = title
            updater.music_properties.artist = artist
            updater.music_properties.album_title = album
            self._apply_cover(cover)
            updater.update()
            self._meta_key = meta_key

        if force or self._playing is None or playing != self._playing:
            if playing:
                self._player.play()
                self._smtc.playback_status = MediaPlaybackStatus.PLAYING
                self._smtc.is_play_enabled = False
                self._smtc.is_pause_enabled = True
            else:
                self._player.pause()
                self._smtc.playback_status = MediaPlaybackStatus.PAUSED
                self._smtc.is_play_enabled = True
                self._smtc.is_pause_enabled = False
            self._playing = playing

        if (force or abs(position - self._position) >= 0.75
                or abs(duration - self._duration) > 0.1):
            timeline = SystemMediaTransportControlsTimelineProperties()
            timeline.start_time = timedelta(seconds=0)
            timeline.end_time = timedelta(seconds=max(0.1, duration))
            timeline.position = timedelta(
                seconds=max(0.0, min(position, max(0.1, duration))))
            self._smtc.update_timeline_properties(timeline)
            self._position = position
            self._duration = duration

    # ----------------------------------------------------------------- close
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._smtc.remove_button_pressed(self._on_button)
            self._smtc.remove_playback_position_change_requested(self._on_seek)
        except Exception:
            pass
        try:
            self._player.pause()
            self._player.source = None
        except Exception:
            pass
        try:
            self._player.close()
        except Exception:
            pass
