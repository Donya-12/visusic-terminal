"""Terminal renderer: header, spectrum, timeline and karaoke lyrics."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import numpy as np

from .lrc import Lyrics

Color = tuple[int, int, int]

WHITE: Color = (240, 246, 255)
TEXT: Color = (196, 206, 222)
DIM: Color = (104, 114, 132)
DIM2: Color = (58, 64, 78)
ACCENT: Color = (110, 240, 198)
ACCENT_DIM: Color = (66, 160, 138)
WARN: Color = (255, 194, 112)
LYRIC_TODO: Color = (98, 108, 126)
LYRIC_CONTEXT: Color = (86, 96, 114)

_EQ_STOPS: tuple[tuple[float, Color], ...] = (
    (0.00, (96, 74, 255)),
    (0.30, (66, 158, 255)),
    (0.58, (64, 232, 222)),
    (0.82, (150, 255, 202)),
    (1.00, (240, 255, 246)),
)

_FULL_HINT = (
    ("space", " pause  "),
    ("←→", " seek  "),
    ("↑↓", " vol  "),
    ("n/p", " track  "),
    ("[ ]", " sync  "),
    ("q", " quit"),
)
_SHORT_HINT = (
    ("spc", " play  "),
    ("←→", " seek  "),
    ("n/p", " next  "),
    ("q", " quit"),
)


@dataclass
class Frame:
    title: str
    artist: str
    index: int = 0
    total: int = 1
    position: float = 0.0
    duration: float = 0.0
    playing: bool = True
    volume: float = 0.75
    bars: np.ndarray = field(default_factory=lambda: np.zeros(32, dtype=np.float32))
    peaks: np.ndarray = field(default_factory=lambda: np.zeros(32, dtype=np.float32))
    lyrics: Lyrics | None = None
    lyric_time: float = 0.0
    lyric_offset: float = 0.0
    status: str = ""


# --------------------------------------------------------------------- canvas
def char_width(ch: str) -> int:
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def text_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


def fit_text(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text
    if width == 1:
        return "…"
    result: list[str] = []
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > width - 1:
            break
        result.append(ch)
        used += w
    return "".join(result) + "…"


def mix(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def eq_color(level: float) -> Color:
    level = max(0.0, min(1.0, level))
    for i in range(1, len(_EQ_STOPS)):
        left_t, left_c = _EQ_STOPS[i - 1]
        right_t, right_c = _EQ_STOPS[i]
        if level <= right_t:
            span = right_t - left_t or 1.0
            return mix(left_c, right_c, (level - left_t) / span)
    return _EQ_STOPS[-1][1]


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class Canvas:
    __slots__ = ("w", "h", "chars", "colors", "bold")

    def __init__(self, width: int, height: int) -> None:
        self.w = width
        self.h = height
        self.chars = [[" "] * width for _ in range(height)]
        self.colors: list[list[Color | None]] = [
            [None] * width for _ in range(height)
        ]
        self.bold = [[False] * width for _ in range(height)]

    def put(self, x: int, y: int, text: str,
            color: Color | None = None, bold: bool = False) -> int:
        if 0 <= y < self.h:
            for ch in text:
                width = char_width(ch)
                if width == 0:
                    if x > 0:
                        self.chars[y][x - 1] += ch
                    continue
                if 0 <= x < self.w:
                    self.chars[y][x] = ch
                    self.colors[y][x] = color
                    self.bold[y][x] = bold
                    if width == 2 and x + 1 < self.w:
                        self.chars[y][x + 1] = ""
                        self.colors[y][x + 1] = color
                x += width
        return x

    def hline(self, y: int, x0: int, x1: int, ch: str,
              color: Color | None = None) -> None:
        if not 0 <= y < self.h:
            return
        for x in range(max(0, x0), min(self.w, x1)):
            self.chars[y][x] = ch
            self.colors[y][x] = color

    def to_lines(self) -> list[str]:
        lines: list[str] = []
        for y in range(self.h):
            parts: list[str] = []
            current: tuple[Color | None, bool] | None = None
            for x in range(self.w):
                ch = self.chars[y][x]
                if ch == "":
                    continue
                style = (self.colors[y][x], self.bold[y][x])
                if style != current:
                    color, bold = style
                    code = "\x1b[0m"
                    if bold:
                        code += "\x1b[1m"
                    if color is not None:
                        code += f"\x1b[38;2;{color[0]};{color[1]};{color[2]}m"
                    parts.append(code)
                    current = style
                parts.append(ch)
            parts.append("\x1b[0m")
            lines.append("".join(parts))
        return lines


# ------------------------------------------------------------------- helpers
def _segments_width(segments: list[tuple[str, Color, bool]]) -> int:
    return sum(text_width(text) for text, _, _ in segments)


def draw_segments(canvas: Canvas, x: int, y: int,
                  segments: list[tuple[str, Color, bool]],
                  max_width: int | None = None) -> int:
    if max_width is None:
        max_width = canvas.w - x
    if max_width <= 0:
        return 0
    remaining = max_width
    drawn = 0
    for text, color, bold in segments:
        if remaining <= 0:
            break
        width = text_width(text)
        if width <= remaining:
            canvas.put(x + drawn, y, text, color, bold)
            drawn += width
            remaining -= width
            continue
        partial = fit_text(text, remaining)
        canvas.put(x + drawn, y, partial, color, bold)
        drawn += text_width(partial)
        remaining = 0
    return drawn


def _draw_right(canvas: Canvas, y: int,
                segments: list[tuple[str, Color, bool]],
                margin: int = 1) -> None:
    total = _segments_width(segments)
    x = canvas.w - margin - total
    draw_segments(canvas, x, y, segments, total)


def _draw_header(canvas: Canvas, frame: Frame) -> None:
    glyph = "▶" if frame.playing else "‖"
    glyph_color = ACCENT if frame.playing else WARN
    right = [(f"{frame.index + 1}/{frame.total}", DIM, False),
             ("  ", DIM, False),
             (glyph, glyph_color, True)]
    right_width = _segments_width(right)
    _draw_right(canvas, 0, right)

    max_left = canvas.w - right_width - 3
    segments: list[tuple[str, Color, bool]] = [("♫", ACCENT, True), (" ", DIM, False)]
    if frame.artist:
        segments.append((frame.artist, DIM, False))
        segments.append((" — ", DIM2, False))
    segments.append((frame.title, WHITE, True))
    draw_segments(canvas, 1, 0, segments, max_left)


def _draw_eq(canvas: Canvas, frame: Frame, top: int, bottom: int) -> None:
    height = bottom - top + 1
    if height <= 0:
        return
    bars = frame.bars
    peaks = frame.peaks
    if bars is None or len(bars) == 0:
        return

    margin = 1
    available = canvas.w - margin * 2
    count = min(len(bars), available)
    if count <= 0:
        return

    slot = max(1, available // count)
    bar_width = 2 if slot >= 3 else 1
    group_width = count * slot - (slot - bar_width)
    offset = margin + max(0, (available - group_width) // 2)
    color_at = (lambda value: mix(eq_color(value), DIM2, 0.45)) if not frame.playing else eq_color

    for i in range(count):
        value = float(bars[i])
        fill = int(round(value * height))
        if value > 0.02 and fill == 0:
            fill = 1
        peak = float(peaks[i]) if i < len(peaks) else 0.0
        peak_row = int(round(peak * max(1, height - 1)))
        x = offset + i * slot + (slot - bar_width) // 2
        if x >= canvas.w:
            break

        block = "█" * bar_width
        for row in range(min(fill, height)):
            level = (row + 1) / height
            canvas.put(x, bottom - row, block, color_at(level))

        if peak_row >= fill and peak > 0.03 and fill < height:
            canvas.put(x, bottom - min(height - 1, peak_row),
                       "▔" * bar_width,
                       mix(WHITE, ACCENT, 0.35) if frame.playing else DIM)


def _draw_timeline(canvas: Canvas, frame: Frame, y: int) -> None:
    left = fmt_time(frame.position)
    right = fmt_time(frame.duration)
    canvas.put(1, y, left, ACCENT_DIM if frame.playing else DIM)

    bar_left = 3 + text_width(left)
    bar_right = canvas.w - 1 - text_width(right) - 1
    bar_width = bar_right - bar_left
    if bar_width >= 4:
        canvas.hline(y, bar_left, bar_right, "─", DIM2)

        lyrics = frame.lyrics
        if lyrics:
            duration = max(0.01, frame.duration)
            step = max(1, len(lyrics.times) // 40)
            for stamp in lyrics.times[::step]:
                stamp += frame.lyric_offset
                if 0.0 <= stamp <= duration:
                    tick = bar_left + int(stamp / duration * (bar_width - 1))
                    if bar_left <= tick < bar_right:
                        canvas.put(tick, y, "·", (78, 86, 102))

        ratio = frame.position / frame.duration if frame.duration > 0 else 0.0
        ratio = max(0.0, min(1.0, ratio))
        filled = int(round(ratio * (bar_width - 1)))
        for x in range(bar_left, bar_left + filled):
            canvas.put(x, y, "━", ACCENT_DIM if frame.playing else DIM)
        head = bar_left + filled
        if 0 <= head < bar_right:
            canvas.put(head, y, "●", ACCENT if frame.playing else TEXT, True)

    right_x = canvas.w - 1 - text_width(right)
    canvas.put(right_x, y, right, DIM)


def _lyric_window(text: str, played: int, max_width: int) -> tuple[str, int, bool, bool]:
    """Return visible text, played offset, and whether ellipses are needed."""
    if max_width <= 2:
        return "", 0, False, False
    if text_width(text) <= max_width:
        return text, played, False, False

    visible = max_width - 2
    start = max(0, played - visible // 3)
    start = min(start, max(0, len(text) - visible))
    end = start + visible
    prefix = start > 0
    suffix = end < len(text)
    if prefix:
        start += 1
        end = start + visible
        suffix = end < len(text)
    view = text[start:end]
    return view, max(0, min(len(view), played - start)), prefix, suffix


def _draw_lyric(canvas: Canvas, y: int, text: str, played: float,
                color_done: Color, color_todo: Color,
                bold_done: bool = True) -> None:
    if not text:
        return
    text = text.replace("\t", " ").strip()
    if not text:
        return

    width = canvas.w - 4
    played_chars = int(round(max(0.0, min(1.0, played)) * len(text)))
    view, offset, prefix, suffix = _lyric_window(text, played_chars, width)
    if not view:
        return

    done = view[:offset]
    todo = view[offset:]
    segments: list[tuple[str, Color, bool]] = []
    if prefix:
        segments.append(("…", DIM2, False))
    if done:
        segments.append((done, color_done, bold_done))
    if todo:
        segments.append((todo, color_todo, False))
    if suffix:
        segments.append(("…", DIM2, False))

    total = _segments_width(segments)
    x = max(1, (canvas.w - total) // 2)
    draw_segments(canvas, x, y, segments, total)


def _draw_lyrics(canvas: Canvas, frame: Frame, prev_y: int, cur_y: int,
                 next_y: int) -> None:
    lyrics = frame.lyrics
    if not lyrics or not lyrics.lines:
        hint = "no lyrics · add a .lrc or run fetch-lyrics.bat"
        hint = fit_text(hint, canvas.w - 2)
        x = max(1, (canvas.w - text_width(hint)) // 2)
        canvas.put(x, cur_y, hint, DIM)
        return

    t = frame.lyric_time
    index = lyrics.index_at(t)
    lines = lyrics.lines

    if index < 0:
        canvas.put(max(1, canvas.w // 2 - 1), cur_y, "♪", ACCENT_DIM)
        next_text = lines[0].text
        _draw_lyric(canvas, next_y, next_text, 0.0, LYRIC_CONTEXT, LYRIC_CONTEXT)
        return

    current = lines[index]
    progress = lyrics.progress(index, t)
    _draw_lyric(canvas, cur_y, current.text, progress, WHITE, LYRIC_TODO)

    if index > 0:
        _draw_lyric(canvas, prev_y, lines[index - 1].text, 1.0,
                    LYRIC_CONTEXT, LYRIC_CONTEXT, False)
    if index + 1 < len(lines):
        _draw_lyric(canvas, next_y, lines[index + 1].text, 0.0,
                    LYRIC_CONTEXT, LYRIC_CONTEXT, False)


def _draw_footer(canvas: Canvas, frame: Frame) -> None:
    y = canvas.h - 1
    right = f"vol {int(round(frame.volume * 100))}%"
    if abs(frame.lyric_offset) >= 0.05:
        right = f"sync {frame.lyric_offset:+.1f}s · {right}"
    right_width = text_width(right)
    show_right = canvas.w >= 56
    limit = canvas.w - (right_width + 3 if show_right else 2)

    if frame.status:
        canvas.put(1, y, fit_text(frame.status, limit), WARN)
    else:
        hints = _FULL_HINT if _segments_width(
            [(key, ACCENT, True) for key, _ in _FULL_HINT]
        ) + sum(text_width(label) for _, label in _FULL_HINT) <= limit else _SHORT_HINT

        x = 1
        for key, label in hints:
            if x >= limit:
                break
            x = canvas.put(x, y, key, ACCENT if frame.playing else DIM, True)
            x = canvas.put(x, y, label, DIM)

    if show_right:
        canvas.put(canvas.w - 1 - right_width, y, right, DIM2)


# -------------------------------------------------------------------- public
def render(frame: Frame, width: int, height: int) -> list[str]:
    if width < 24 or height < 8:
        message = "terminal too small"
        canvas = Canvas(max(width, 1), max(height, 1))
        canvas.put(0, 0, message[:width], DIM)
        return canvas.to_lines()

    canvas = Canvas(width, height)

    if height < 14:
        _draw_header(canvas, frame)
        canvas.hline(1, 1, width - 1, "─", DIM2)
        eq_bottom = height - 8
        if eq_bottom >= 2:
            _draw_eq(canvas, frame, 2, eq_bottom)
        _draw_timeline(canvas, frame, height - 6)
        _draw_lyrics(canvas, frame, height - 5, height - 4, height - 3)
        _draw_footer(canvas, frame)
        return canvas.to_lines()

    lyric_next = height - 3
    lyric_cur = height - 4
    lyric_prev = height - 5
    timeline_y = height - 7
    eq_bottom = timeline_y - 2
    eq_height = min(24, height - 11)
    eq_top = eq_bottom - eq_height + 1

    _draw_header(canvas, frame)
    canvas.hline(1, 1, width - 1, "─", DIM2)
    _draw_eq(canvas, frame, eq_top, eq_bottom)
    _draw_timeline(canvas, frame, timeline_y)
    _draw_lyrics(canvas, frame, lyric_prev, lyric_cur, lyric_next)
    _draw_footer(canvas, frame)
    return canvas.to_lines()