"""Discord Rich Presence (optional, needs a Discord Application ID)."""

from __future__ import annotations

import os
import time

from .theme import load_setting, save_setting

try:
    from pypresence import Presence
    from pypresence.types import ActivityType

    _PRESENCE_ERROR: Exception | None = None
except Exception as exc:
    Presence = None  # type: ignore[assignment]
    ActivityType = None  # type: ignore[assignment]
    _PRESENCE_ERROR = exc

SETTING = "discord_client_id"
DEFAULT_CLIENT_ID = "1575611266486239292"
UPDATE_INTERVAL = 2.0
RETRY_INTERVAL = 30.0


def valid_client_id(value: str | None) -> bool:
    return bool(value) and value.isdigit() and 15 <= len(value) <= 25


def load_client_id() -> str:
    env = os.environ.get("VISUSIC_DISCORD_ID", "").strip()
    if valid_client_id(env):
        return env
    value = str(load_setting(SETTING, "") or "").strip()
    if valid_client_id(value):
        return value
    return DEFAULT_CLIENT_ID


def save_client_id(value: str) -> bool:
    value = value.strip()
    if not valid_client_id(value):
        return False
    return save_setting(SETTING, value)


def build_activity(*, title: str, artist: str, album: str,
                   position: float, duration: float, playing: bool,
                   image: str = "", now: float | None = None) -> dict:
    now = time.time() if now is None else now
    title = (title or "VisuSic Terminal").strip()
    artist = (artist or "").strip()
    album = (album or "").strip()
    details = f"♪ {title}"[:128]
    trail = " · ".join(part for part in (artist, album) if part)
    if playing:
        state = (trail or "VisuSic Terminal")[:128]
    else:
        state = (f"Paused · {trail}" if trail else "Paused")[:128]

    activity = {
        "details": details,
        "state": state,
        "large_text": "VisuSic Terminal · terminal music visualizer",
        "instance": False,
    }
    if image:
        activity["large_image"] = image

    if playing and duration > 0:
        position = max(0.0, min(position, duration))
        activity["start"] = int(now - position)
        if position < duration:
            activity["end"] = int(now + duration - position)
    return activity


class DiscordPresence:
    def __init__(self, client_id: str, image: str = "") -> None:
        if _PRESENCE_ERROR is not None:
            raise RuntimeError(f"pypresence is unavailable: {_PRESENCE_ERROR}")
        if not valid_client_id(client_id):
            raise ValueError("invalid Discord client ID")
        self.client_id = client_id
        self.image = image.strip()
        self._rpc = None
        self._last_key: tuple[str, str, str, bool] | None = None
        self._last_sent = 0.0
        self._next_connect = 0.0
        self._pending = False
        self._closed = False

    def _connect(self) -> bool:
        if self._closed or Presence is None:
            return False
        now = time.monotonic()
        if now < self._next_connect:
            return False
        try:
            rpc = Presence(self.client_id)
            rpc.connect()
        except Exception:
            self._next_connect = now + RETRY_INTERVAL
            self._rpc = None
            return False
        self._rpc = rpc
        self._last_key = None
        self._pending = True
        return True

    def _disconnect(self) -> None:
        rpc, self._rpc = self._rpc, None
        self._next_connect = time.monotonic() + RETRY_INTERVAL
        if rpc is not None:
            try:
                rpc.close()
            except Exception:
                pass

    def update(self, *, title: str, artist: str, album: str,
               position: float, duration: float, playing: bool,
               force: bool = False) -> None:
        if self._closed:
            return
        if self._rpc is None and not self._connect():
            return

        key = (title.strip(), artist.strip(), album.strip(), playing)
        if not force and not self._pending and key == self._last_key:
            return

        now = time.monotonic()
        if now - self._last_sent < UPDATE_INTERVAL:
            self._pending = True
            return

        activity = build_activity(
            title=title, artist=artist, album=album,
            position=position, duration=duration, playing=playing,
            image=self.image,
        )
        try:
            kwargs = dict(activity)
            if ActivityType is not None:
                kwargs["activity_type"] = ActivityType.LISTENING
            self._rpc.update(**kwargs)
        except Exception:
            self._disconnect()
            return

        self._last_key = key
        self._last_sent = now
        self._pending = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        rpc, self._rpc = self._rpc, None
        if rpc is not None:
            try:
                rpc.clear()
            except Exception:
                pass
            try:
                rpc.close()
            except Exception:
                pass
