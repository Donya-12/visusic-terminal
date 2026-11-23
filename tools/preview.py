"""Development helper: render one frame to an HTML preview.

Usage: python tools/preview.py [width] [height]
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from visusic.lrc import parse  # noqa: E402
from visusic.spectrum import bands_for_width  # noqa: E402
from visusic.ui import Frame, render  # noqa: E402

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
        bold = False
        position = 0
        for match in ANSI.finditer(line):
            chunk = line[position:match.start()]
            if chunk:
                style = ""
                if color:
                    style += f"color:{color};"
                if bold:
                    style += "font-weight:700;"
                parts.append(f"<span style=\"{style}\">{html.escape(chunk)}</span>")
            codes = match.group(1).split(";")
            if match.group(1) in ("", "0"):
                color, bold = None, False
            else:
                i = 0
                while i < len(codes):
                    code = codes[i]
                    if code == "1":
                        bold = True
                    elif code == "38" and i + 4 < len(codes) and codes[i + 1] == "2":
                        color = "#{:02x}{:02x}{:02x}".format(
                            int(codes[i + 2]), int(codes[i + 3]), int(codes[i + 4])
                        )
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


def main() -> None:
    width = int(sys.argv[1]) if len(sys.argv) > 1 else 119
    height = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    frame = sample_frame(bands_for_width(width))
    lines = render(frame, width, height)
    body = ansi_to_html(lines)

    page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>VisuSic Terminal — preview</title>
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
    target = Path(__file__).resolve().parents[1] / "docs" / "preview.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()

