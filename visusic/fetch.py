"""Download synced .lrc lyrics from LRCLIB for a folder of tracks.

This is an optional helper: the player itself stays offline.  It never
overwrites an existing .lrc unless --overwrite is passed.
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
from pathlib import Path

import soundfile as sf

from . import __version__
from .library import Track, scan

API = "https://lrclib.net/api/search"
USER_AGENT = f"VisuSic-Terminal/{__version__} (local lyrics helper)"
TIMEOUT = 20.0
MAX_CONSECUTIVE_ERRORS = 3


def _normalize(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return " ".join(cleaned.split())


def _similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _duration(path: Path) -> float | None:
    try:
        return float(sf.info(path).duration)
    except Exception:
        return None


def _search(track: Track, timeout: float) -> list[dict]:
    params = {"track_name": track.title}
    if track.artist:
        params["artist_name"] = track.artist
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def _score(item: dict, track: Track, duration: float | None) -> int:
    if not item.get("syncedLyrics") or item.get("instrumental"):
        return -100

    title = _normalize(track.title)
    artist = _normalize(track.artist)
    found_title = _normalize(str(item.get("trackName") or ""))
    found_artist = _normalize(str(item.get("artistName") or ""))

    score = 0
    if title and found_title == title:
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

    found_duration = item.get("duration")
    if duration is not None and isinstance(found_duration, (int, float)):
        difference = abs(float(found_duration) - duration)
        if difference <= 2:
            score += 4
        elif difference <= 5:
            score += 2
        elif difference > 20:
            score -= 3

    return score


def _pick(results: list[dict], track: Track,
          duration: float | None) -> dict | None:
    best: dict | None = None
    best_score = 5  # require at least "title matched + something"
    for item in results:
        score = _score(item, track, duration)
        if score > best_score:
            best, best_score = item, score
    return best


def _fetch_one(track: Track, timeout: float) -> tuple[str, str]:
    """Return (status, message), status in saved/skip/miss/error."""
    lrc_path = track.path.with_suffix(".lrc")
    duration = _duration(track.path)
    results = _search(track, timeout)
    match = _pick(results, track, duration)
    if match is None:
        return "miss", "no synced lyrics found"

    text = str(match["syncedLyrics"]).strip()
    if not text:
        return "miss", "empty sync data"

    found = f"{match.get('artistName')} — {match.get('trackName')}"
    lrc_path.write_text(text + "\n", encoding="utf-8")
    return "saved", found


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visusic-fetch",
        description="Download synced .lrc lyrics from LRCLIB for audio files.",
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="audio file or folder (default: current folder)")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N downloaded lyric files (0 = all)")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace existing .lrc files")
    parser.add_argument("--dry-run", action="store_true",
                        help="search and report without writing files")
    parser.add_argument("--delay", type=float, default=0.6,
                        help="pause between requests in seconds (default: 0.6)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT,
                        help="network timeout in seconds (default: 20)")
    parser.add_argument("--version", action="version",
                        version=f"visusic-fetch {__version__}")
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

    print(f"Tracks: {len(tracks)} · source: LRCLIB · "
          f"{'dry run' if args.dry_run else 'writing .lrc'}")
    saved = existing = missed = failed = 0
    consecutive_errors = 0
    delay = max(0.0, args.delay)

    for index, track in enumerate(tracks, 1):
        lrc_path = track.path.with_suffix(".lrc")
        if lrc_path.exists() and not args.overwrite:
            existing += 1
            print(f"[{index}/{len(tracks)}] skip, .lrc exists: {track.display}")
            continue

        label = f"[{index}/{len(tracks)}] {track.display}"
        try:
            if args.dry_run:
                duration = _duration(track.path)
                match = _pick(_search(track, args.timeout), track, duration)
                if match:
                    print(f"{label} -> {match.get('artistName')} — "
                          f"{match.get('trackName')}")
                    saved += 1
                else:
                    print(f"{label} -> no synced lyrics")
                    missed += 1
                consecutive_errors = 0
            else:
                status, message = _fetch_one(track, args.timeout)
                if status == "saved":
                    saved += 1
                    print(f"{label} -> saved: {message}")
                elif status == "miss":
                    missed += 1
                    print(f"{label} -> {message}")
                consecutive_errors = 0
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                missed += 1
                print(f"{label} -> no lyrics (404)")
                consecutive_errors = 0
            elif exc.code == 429:
                failed += 1
                consecutive_errors += 1
                print(f"{label} -> rate limited, pause 5 s")
                time.sleep(5.0)
            else:
                failed += 1
                consecutive_errors += 1
                print(f"{label} -> HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failed += 1
            consecutive_errors += 1
            print(f"{label} -> network error: {exc}")

        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            print("Too many network errors in a row, stopping. "
                  "Check the connection and run again.")
            break

        if args.limit and saved >= args.limit:
            print(f"Limit reached: {args.limit}.")
            break

        if delay:
            time.sleep(delay)

    print()
    print(f"Saved: {saved} · already had .lrc: {existing} · "
          f"not found: {missed} · errors: {failed}")
    if args.dry_run:
        print("Dry run: no files were written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
