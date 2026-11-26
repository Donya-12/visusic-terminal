"""Development helper: render one frame to an HTML preview.

Usage: python tools/preview.py [width] [height] [--theme NAME] [--menu N] [--out PATH]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from visusic.lrc import parse  # noqa: E402
from visusic.spectrum import bands_for_width  # noqa: E402
from visusic.theme import get_theme, theme_names  # noqa: E402
from visusic.ui import Frame, PlaylistRow, PlaylistView, render  # noqa: E402

ANSI = re.compile(r"\x1b\[([0-9;]*)m")
SAMPLE_LRC = """[ar:Неоновые волны]
[ti:Полночный драйв]
[al:Terminal Sessions]
[00:00.50]Город спит, а мы не спим
[00:12.00]Неоновые волны впереди
[00:24.00]Держи ритм со мной
[00:36.00]Мы едем в ночь, где нет границ
[01:44.00]Свет фонарей плывёт за стеклом
[01:52.00]<01:52.00>Мы <01:52.55>едем <01:53.20>в <01:53.60>ночь, <01:54.10>где <01:54.60>нет <01:55.10>границ
[02:00.00]И фары режут тишину
[02:16.00]Неоновые волны впереди
"""


def ansi_to_html(lines: list[str]) -> str:
    rows: list[str] = []
    for line in lines:
        parts: list[str] = []
        color: str | None = None
        background: str | None = None
        bold = False
        position = 0
        for match in ANSI.finditer(line):
            chunk = line[position:match.start()]
            if chunk:
                style = ""
                if color:
                    style += f"color:{color};"
                if background:
                    style += f"background-color:{background};"
                if bold:
                    style += "font-weight:700;"
                parts.append(f"<span style=\"{style}\">{html.escape(chunk)}</span>")
            codes = match.group(1).split(";")
            if match.group(1) in ("", "0"):
                color, background, bold = None, None, False
            else:
                i = 0
                while i < len(codes):
                    code = codes[i]
                    if code == "1":
                        bold = True
                    elif code in ("38", "48") and i + 4 < len(codes) and codes[i + 1] == "2":
                        value = "#{:02x}{:02x}{:02x}".format(
                            int(codes[i + 2]), int(codes[i + 3]), int(codes[i + 4])
                        )
                        if code == "38":
                            color = value
                        else:
                            background = value
                        i += 4
                    i += 1
            position = match.end()
        tail = line[position:]
        if tail:
            parts.append(html.escape(tail))
        rows.append(f"<div>{''.join(parts)}</div>")
    return "\n".join(rows)


def sample_frame(bands: int = 38) -> Frame:
    rng = np.random.default_rng(7)
    count = bands
    x = np.linspace(0.0, 1.0, count)
    envelope = (
        0.92 * np.exp(-((x - 0.12) / 0.20) ** 2)
        + 0.72 * np.exp(-((x - 0.38) / 0.16) ** 2)
        + 0.48 * np.exp(-((x - 0.63) / 0.20) ** 2)
        + 0.30 * np.exp(-((x - 0.85) / 0.16) ** 2)
    )
    bars = np.clip(
        envelope * (0.62 + 0.38 * rng.random(count)) + rng.normal(0, 0.035, count),
        0.02, 1.0,
    ).astype(np.float32)
    peaks = np.clip(bars + 0.07, 0.0, 1.0)

    return Frame(
        title="Полночный драйв",
        artist="Неоновые волны",
        index=4,
        total=12,
        position=113.4,
        duration=241.0,
        playing=True,
        volume=0.75,
        bars=bars,
        peaks=peaks,
        lyrics=parse(SAMPLE_LRC),
        lyric_time=113.4,
    )


def sample_playlist(theme, selected: int = 2) -> PlaylistView:
    items = [
        ("Neon Waves", "Midnight Drive", "Terminal Sessions", 241.0),
        ("The Same Stars", "City Lights", "Night Drive", 208.0),
        ("8-Bit Bunker", "My Time", "Arcade Heart", 201.0),
        ("Adventure Time", "Island Song", "Come Along with Me", 109.0),
        ("ABBA", "The Winner Takes It All", "The Essential Collection", 295.0),
        ("Chrome Hearts", "Static Bloom", "Afterglow", 187.0),
        ("Mono Lake", "Slow Motion", "Blue Hour", 264.0),
        ("Synth Coast", "Last Train", "Neon Tapes", 223.0),
    ]
    rows = []
    for index, (artist, title, album, duration) in enumerate(items):
        cover = []
        for y in range(3):
            cover.append([
                theme.eq_color(0.15 + 0.7 * ((index * 3 + x + y * 2) % 9) / 8)
                for x in range(8)
            ])
        rows.append(PlaylistRow(
            index=index, title=title, artist=artist, album=album,
            duration=duration, cover=cover, current=index == 0,
            loaded=True,
        ))
    return PlaylistView(rows=rows, selected=selected, current=0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one VisuSic frame to HTML")
    parser.add_argument("width", nargs="?", type=int, default=119)
    parser.add_argument("height", nargs="?", type=int, default=30)
    parser.add_argument("--theme", choices=theme_names(), default="aurora")
    parser.add_argument("--menu", type=int, default=None,
                        help="show the theme menu with this preset selected")
    parser.add_argument("--playlist", action="store_true",
                        help="show the playlist overlay")
    parser.add_argument("--out", default="docs/preview.html")
    parser.add_argument("--title", default="VisuSic Terminal — preview")
    args = parser.parse_args()

    width, height = args.width, args.height
    frame = sample_frame(bands_for_width(width))
    theme = get_theme(args.theme)
    playlist = sample_playlist(theme) if args.playlist else None
    lines = render(frame, width, height, theme, menu=args.menu,
                   playlist=playlist)
    body = ansi_to_html(lines)
    if args.menu is not None:
        args.title = f"{args.title} · themes"
    if args.playlist:
        args.title = f"{args.title} · playlist"

    page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>{html.escape(args.title)}</title>
<style>
  html, body {{ margin: 0; background: #05070b; }}
  body {{ padding: 28px; font-family: "Cascadia Mono", Consolas, monospace; }}
  .window {{
    max-width: {width * 10 + 24}px; margin: 0 auto; background: #0a0d14;
    border: 1px solid #232a36; border-radius: 12px; overflow: hidden;
    box-shadow: 0 24px 80px rgba(0,0,0,.55);
  }}
  .titlebar {{
    height: 34px; display: flex; align-items: center; gap: 8px; padding: 0 14px;
    background: #0e1219; border-bottom: 1px solid #1c2330; color: #7d889b;
    font-size: 12px; letter-spacing: .04em;
  }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #2a3140; }}
  .screen {{
    padding: 14px 16px 16px; font-size: 16px; line-height: 1.0;
    color: #c4ceda; tab-size: 4;
    font-variant-ligatures: none; letter-spacing: 0;
  }}
  .screen div {{ height: 16px; line-height: 16px; white-space: pre; }}
</style>
</head>
<body>
  <div class="window">
    <div class="titlebar"><span class="dot"></span><span class="dot"></span>
      <span class="dot"></span><span style="margin-left:8px">VisuSic Terminal — Windows Terminal</span>
    </div>
    <div class="screen">
{body}
    </div>
  </div>
</body>
</html>
"""
    target = Path(args.out)
    if not target.is_absolute():
        target = Path(__file__).resolve().parents[1] / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()


