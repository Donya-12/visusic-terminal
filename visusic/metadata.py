"""Track metadata and cover art: tags first, sidecar files second."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from mutagen import File as MutagenFile


@dataclass(frozen=True)
class TrackInfo:
    artist: str
    title: str
    album: str
    duration: float | None


_INFO_CACHE: dict[tuple[str, int, str, str], TrackInfo] = {}
_COVER_CACHE: dict[tuple[str, int], bytes | None] = {}
_MOSAIC_CACHE: dict[tuple[str, int, int, int], list[list[tuple[int, int, int]]] | None] = {}


def _stamp(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _first(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    return str(value).strip()


def read_info(path: Path, fallback_artist: str = "",
              fallback_title: str = "") -> TrackInfo:
    stamp = _stamp(path)
    key = (str(path), stamp, fallback_artist, fallback_title)
    cached = _INFO_CACHE.get(key)
    if cached is not None:
        return cached

    artist = fallback_artist
    title = fallback_title
    album = ""
    duration = None
    audio = None
    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            tags = audio.tags or {}
            artist = _first(tags.get("artist")) or artist
            title = _first(tags.get("title")) or title
            album = _first(tags.get("album"))
            if getattr(audio, "info", None) is not None:
                duration = float(audio.info.length)
    except Exception:
        pass

    info = TrackInfo(artist=artist, title=title, album=album,
                     duration=duration)
    _INFO_CACHE[key] = info
    return info


def _embedded_cover(audio) -> bytes | None:
    pictures = getattr(audio, "pictures", None)
    if pictures:
        try:
            return bytes(pictures[0].data)
        except Exception:
            pass

    tags = getattr(audio, "tags", None)
    if tags is None:
        return None

    try:
        apics = tags.getall("APIC")
        if apics:
            return bytes(apics[0].data)
    except Exception:
        pass

    try:
        covers = tags.get("covr")
        if covers:
            return bytes(covers[0])
    except Exception:
        pass

    try:
        pictures = tags.get("metadata_block_picture")
        if pictures:
            from mutagen.flac import Picture

            return Picture(base64.b64decode(pictures[0])).data
    except Exception:
        pass

    return None


def sidecar_cover(path: Path) -> Path | None:
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = path.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    for stem in ("cover", "folder", "front", "album"):
        for suffix in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = path.parent / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def embedded_cover(path: Path) -> bytes | None:
    try:
        audio = MutagenFile(path)
    except Exception:
        return None
    if audio is None:
        return None
    return _embedded_cover(audio)


def cover_bytes(path: Path) -> bytes | None:
    stamp = _stamp(path)
    key = (str(path), stamp)
    if key in _COVER_CACHE:
        return _COVER_CACHE[key]

    data = embedded_cover(path)
    if not data:
        sidecar = sidecar_cover(path)
        if sidecar is not None:
            try:
                data = sidecar.read_bytes()
            except OSError:
                data = None

    _COVER_CACHE[key] = data
    return data


def cover_mosaic(path: Path, cols: int = 6, rows: int = 3,
                 ) -> list[list[tuple[int, int, int]]] | None:
    stamp = _stamp(path)
    key = (str(path), stamp, cols, rows)
    if key in _MOSAIC_CACHE:
        return _MOSAIC_CACHE[key]

    data = cover_bytes(path)
    result = None
    if data:
        try:
            from PIL import Image

            image = Image.open(BytesIO(data)).convert("RGB")
            width, height = image.size
            side = min(width, height)
            left = (width - side) // 2
            top = (height - side) // 2
            image = image.crop((left, top, left + side, top + side))
            image = image.resize((cols, rows), Image.Resampling.LANCZOS)
            result = [
                [image.getpixel((x, y)) for x in range(cols)]
                for y in range(rows)
            ]
        except Exception:
            result = None

    _MOSAIC_CACHE[key] = result
    return result


def has_cover(path: Path) -> bool:
    return cover_bytes(path) is not None


def clear_caches() -> None:
    _INFO_CACHE.clear()
    _COVER_CACHE.clear()
    _MOSAIC_CACHE.clear()
