"""Download album covers from the iTunes Search API.

Optional helper, like the LRCLIB lyrics fetch: the player itself stays offline.
Covers are saved next to the audio as ``<track>.jpg`` and picked up on the next
track load.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from . import metadata
from . import __version__
from .library import Track, scan

API = "https://itunes.apple.com/search"
USER_AGENT = f"VisuSic-Terminal/{__version__} (cover helper)"
TIMEOUT = 20.0
MAX_ERRORS = 3
_ART_SIZE = re.compile(r"/\d+x\d+bb\.")


def _normalize(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return " ".join(cleaned.split())


def _similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _search(track: Track, info: metadata.TrackInfo, timeout: float) -> list[dict]:
    artist = info.artist or track.artist
    title = info.title or track.title
    params = {
        "term": f"{artist} {title}".strip(),
        "media": "music",
        "entity": "song",
        "limit": "10",
    }
    request = urllib.request.Request(
        API + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("results", []) if isinstance(data, dict) else []


def _score(item: dict, track: Track, info: metadata.TrackInfo) -> int:
    title = _normalize(info.title or track.title)
    artist = _normalize(info.artist or track.artist)
    found_title = _normalize(str(item.get("trackName") or ""))
    found_artist = _normalize(str(item.get("artistName") or ""))
    if not item.get("artworkUrl100") or not title:
        return -100

    score = 0
    if found_title == title:
        score += 6
    elif _similar(title, found_title):
        score += 3
    else:
        return -100

    if artist:
        if found_artist == artist:
            score += 4
        elif _similar(artist, found_artist):
            score += 1
        else:
            score -= 2

    duration = info.duration
    found_ms = item.get("trackTimeMillis")
    if duration and isinstance(found_ms, (int, float)):
        difference = abs(found_ms / 1000.0 - duration)
        if difference <= 2:
            score += 4
        elif difference <= 5:
            score += 2
        elif difference > 20:
            score -= 3

    return score


def _pick(results: list[dict], track: Track,
          info: metadata.TrackInfo) -> dict | None:
    best: dict | None = None
    best_score = 6
    for item in results:
        score = _score(item, track, info)
        if score > best_score:
            best, best_score = item, score
    return best


def _artwork_url(item: dict) -> str | None:
    url = item.get("artworkUrl100")
    if not url:
        return None
    return _ART_SIZE.sub("/600x600bb.", str(url)).replace(
        "/100x100bb.", "/600x600bb.")


def _download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _save_cover(path: Path, data: bytes) -> None:
    from PIL import Image

    image = Image.open(BytesIO(data)).convert("RGB")
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((600, 600), Image.Resampling.LANCZOS)
    image.save(path.with_suffix(".jpg"), "JPEG", quality=92, optimize=True)


def _fetch_one(track: Track, timeout: float) -> tuple[str, str]:
    info = metadata.read_info(track.path, track.artist, track.title)
    results = _search(track, info, timeout)
    match = _pick(results, track, info)
    if match is None:
        return "miss", "no matching artwork"
    url = _artwork_url(match)
    if not url:
        return "miss", "no artwork URL"
    data = _download(url, timeout)
    _save_cover(track.path, data)
    return "saved", f"{match.get('artistName')} — {match.get('collectionName')}"


def _skip_reason(path: Path, overwrite: bool) -> str | None:
    embedded = metadata.embedded_cover(path)
    if embedded:
        return "embedded cover already present"
    sidecar = metadata.sidecar_cover(path)
    if sidecar and not overwrite:
        return "sidecar cover already present"
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visusic-covers",
        description="Download album covers from iTunes for audio files.",
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="audio file or folder (default: current folder)")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N downloaded covers (0 = all)")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace an existing sidecar .jpg")
    parser.add_argument("--dry-run", action="store_true",
                        help="search and report without writing covers")
    parser.add_argument("--delay", type=float, default=0.6,
                        help="pause between requests in seconds (default: 0.6)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT,
                        help="network timeout in seconds (default: 20)")
    parser.add_argument("--version", action="version",
                        version=f"visusic-covers {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    target = Path(args.path).expanduser()
    if not target.exists():
        print(f"Path not found: {target}")
        return 2

    tracks = scan(target)
    if not tracks and args.path == ".":
        music = Path.home() / "Music"
        if music.is_dir() and music.resolve() != target.resolve():
            fallback = scan(music)
            if fallback:
                target, tracks = music, fallback
    if not tracks:
        print(f"No audio files found in {target}")
        return 2

    print(f"Tracks: {len(tracks)} · source: iTunes · "
          f"{'dry run' if args.dry_run else 'writing covers'}")
    saved = existing = missed = failed = 0
    errors = 0
    delay = max(0.0, args.delay)

    for index, track in enumerate(tracks, 1):
        reason = _skip_reason(track.path, args.overwrite)
        if reason:
            existing += 1
            print(f"[{index}/{len(tracks)}] skip, {reason}: {track.display}")
            continue

        label = f"[{index}/{len(tracks)}] {track.display}"
        try:
            if args.dry_run:
                info = metadata.read_info(track.path, track.artist, track.title)
                match = _pick(_search(track, info, args.timeout), track, info)
                if match:
                    print(f"{label} -> {match.get('artistName')} — "
                          f"{match.get('collectionName')}")
                    saved += 1
                else:
                    print(f"{label} -> no matching artwork")
                    missed += 1
            else:
                status, message = _fetch_one(track, args.timeout)
                if status == "saved":
                    saved += 1
                    print(f"{label} -> saved: {message}")
                else:
                    missed += 1
                    print(f"{label} -> {message}")
            errors = 0
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                missed += 1
                print(f"{label} -> not found (404)")
                errors = 0
            elif exc.code == 429:
                failed += 1
                errors += 1
                print(f"{label} -> rate limited, pause 5 s")
                time.sleep(5.0)
            else:
                failed += 1
                errors += 1
                print(f"{label} -> HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failed += 1
            errors += 1
            print(f"{label} -> network error: {exc}")

        if errors >= MAX_ERRORS:
            print("Too many network errors in a row, stopping.")
            break
        if args.limit and saved >= args.limit:
            print(f"Limit reached: {args.limit}.")
            break
        if delay:
            time.sleep(delay)

    print()
    print(f"Saved: {saved} · already had cover: {existing} · "
          f"not found: {missed} · errors: {failed}")
    if args.dry_run:
        print("Dry run: no files were written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
