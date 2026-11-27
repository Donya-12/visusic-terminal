"""Terminal renderer: header, spectrum, timeline, karaoke and theme menu."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import numpy as np

from .equalizer import BANDS, EQ_LIST, MAX_GAIN, clamp_gains
from .lrc import Lyrics
from .theme import (
    Color,
    DEFAULT_THEME,
    THEMES,
    Theme,
    get_theme,
    mix,
)

_DEFAULT = get_theme(DEFAULT_THEME)

# Backward-compatible default palette for tooling and simple callers.
WHITE: Color = _DEFAULT.white
TEXT: Color = _DEFAULT.text
DIM: Color = _DEFAULT.dim
DIM2: Color = _DEFAULT.dim2
ACCENT: Color = _DEFAULT.accent
ACCENT_DIM: Color = _DEFAULT.accent_dim
WARN: Color = _DEFAULT.warn
LYRIC_TODO: Color = _DEFAULT.lyric_todo
LYRIC_CONTEXT: Color = _DEFAULT.lyric_context


def eq_color(level: float) -> Color:
    """Default-theme gradient, kept for tooling."""
    return _DEFAULT.eq_color(level)


_FULL_HINT = (
    ("space", " pause  "),
    ("←→", " seek  "),
    ("↑↓", " vol  "),
    ("n/p", " track  "),
    ("[ ]", " sync  "),
    ("t", " theme  "),
    ("l", " list  "),
    ("e/m", " eq  "),
    ("q", " quit"),
)
_SHORT_HINT = (
    ("spc", " play  "),
    ("←→", " seek  "),
    ("n/p", " next  "),
    ("l/t/e", " menu  "),
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


@dataclass
class PlaylistRow:
    index: int
    title: str
    artist: str = ""
    album: str = ""
    duration: float | None = None
    cover: list[list[Color]] | None = None
    current: bool = False
    loaded: bool = False


@dataclass
class PlaylistView:
    rows: list[PlaylistRow]
    selected: int
    current: int


@dataclass
class EQEditorView:
    gains: list[float]
    band: int = 0
    label: str = "Custom"


def _fmt_gain(value: float) -> str:
    if abs(value) < 0.05:
        return "0"
    text = f"{value:+.1f}"
    return text[:-2] if text.endswith(".0") else text


def _band_label(index: int) -> str:
    hertz = BANDS[index]
    return f"{hertz // 1000}k" if hertz >= 1000 else str(hertz)


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


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class Canvas:
    __slots__ = ("w", "h", "chars", "colors", "bgs", "bold")

    def __init__(self, width: int, height: int) -> None:
        self.w = width
        self.h = height
        self.chars = [[" "] * width for _ in range(height)]
        self.colors: list[list[Color | None]] = [
            [None] * width for _ in range(height)
        ]
        self.bgs: list[list[Color | None]] = [
            [None] * width for _ in range(height)
        ]
        self.bold = [[False] * width for _ in range(height)]

    def put(self, x: int, y: int, text: str,
            color: Color | None = None, bold: bool = False,
            bg: Color | None = None) -> int:
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
                    self.bgs[y][x] = bg
                    self.bold[y][x] = bold
                    if width == 2 and x + 1 < self.w:
                        self.chars[y][x + 1] = ""
                        self.colors[y][x + 1] = color
                        self.bgs[y][x + 1] = bg
                x += width
        return x

    def rect(self, x0: int, y0: int, x1: int, y1: int, ch: str = " ",
             color: Color | None = None, bold: bool = False,
             bg: Color | None = None) -> None:
        for y in range(max(0, y0), min(self.h, y1)):
            for x in range(max(0, x0), min(self.w, x1)):
                self.chars[y][x] = ch
                self.colors[y][x] = color
                self.bgs[y][x] = bg
                self.bold[y][x] = bold

    def dim(self, factor: float = 0.4) -> None:
        for y in range(self.h):
            for x in range(self.w):
                color = self.colors[y][x]
                if color is not None:
                    self.colors[y][x] = (
                        int(color[0] * factor),
                        int(color[1] * factor),
                        int(color[2] * factor),
                    )
                bg = self.bgs[y][x]
                if bg is not None:
                    self.bgs[y][x] = (
                        int(bg[0] * factor),
                        int(bg[1] * factor),
                        int(bg[2] * factor),
                    )

    def hline(self, y: int, x0: int, x1: int, ch: str,
              color: Color | None = None) -> None:
        if not 0 <= y < self.h:
            return
        for x in range(max(0, x0), min(self.w, x1)):
            self.chars[y][x] = ch
            self.colors[y][x] = color
            self.bgs[y][x] = None

    def to_lines(self) -> list[str]:
        lines: list[str] = []
        for y in range(self.h):
            parts: list[str] = []
            current: tuple[Color | None, Color | None, bool] | None = None
            for x in range(self.w):
                ch = self.chars[y][x]
                if ch == "":
                    continue
                style = (self.colors[y][x], self.bgs[y][x], self.bold[y][x])
                if style != current:
                    color, bg, bold = style
                    code = "\x1b[0m"
                    if bold:
                        code += "\x1b[1m"
                    if color is not None:
                        code += f"\x1b[38;2;{color[0]};{color[1]};{color[2]}m"
                    if bg is not None:
                        code += f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m"
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


def _draw_header(canvas: Canvas, frame: Frame, theme: Theme) -> None:
    glyph = "▶" if frame.playing else "‖"
    glyph_color = theme.accent if frame.playing else theme.warn
    right = [(f"{frame.index + 1}/{frame.total}", theme.dim, False),
             ("  ", theme.dim, False),
             (glyph, glyph_color, True)]
    right_width = _segments_width(right)
    _draw_right(canvas, 0, right)

    max_left = canvas.w - right_width - 3
    segments: list[tuple[str, Color, bool]] = [
        ("♫", theme.accent, True), (" ", theme.dim, False)
    ]
    if frame.artist:
        segments.append((frame.artist, theme.dim, False))
        segments.append((" — ", theme.dim2, False))
    segments.append((frame.title, theme.white, True))
    draw_segments(canvas, 1, 0, segments, max_left)


def _draw_eq(canvas: Canvas, frame: Frame, theme: Theme,
             top: int, bottom: int) -> None:
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

    def color_at(value: float) -> Color:
        color = theme.eq_color(value)
        return color if frame.playing else mix(color, theme.dim2, 0.45)

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
            cap = mix(theme.white, theme.accent, 0.35) if frame.playing else theme.dim
            canvas.put(x, bottom - min(height - 1, peak_row),
                       "▔" * bar_width, cap)


def _draw_timeline(canvas: Canvas, frame: Frame, theme: Theme, y: int) -> None:
    left = fmt_time(frame.position)
    right = fmt_time(frame.duration)
    canvas.put(1, y, left, theme.accent_dim if frame.playing else theme.dim)

    bar_left = 3 + text_width(left)
    bar_right = canvas.w - 1 - text_width(right) - 1
    bar_width = bar_right - bar_left
    if bar_width >= 4:
        canvas.hline(y, bar_left, bar_right, "─", theme.dim2)

        lyrics = frame.lyrics
        if lyrics:
            duration = max(0.01, frame.duration)
            step = max(1, len(lyrics.times) // 40)
            tick_color = mix(theme.dim2, theme.dim, 0.45)
            for stamp in lyrics.times[::step]:
                stamp += frame.lyric_offset
                if 0.0 <= stamp <= duration:
                    tick = bar_left + int(stamp / duration * (bar_width - 1))
                    if bar_left <= tick < bar_right:
                        canvas.put(tick, y, "·", tick_color)

        ratio = frame.position / frame.duration if frame.duration > 0 else 0.0
        ratio = max(0.0, min(1.0, ratio))
        filled = int(round(ratio * (bar_width - 1)))
        fill_color = theme.accent_dim if frame.playing else theme.dim
        for x in range(bar_left, bar_left + filled):
            canvas.put(x, y, "━", fill_color)
        head = bar_left + filled
        if 0 <= head < bar_right:
            head_color = theme.accent if frame.playing else theme.text
            canvas.put(head, y, "●", head_color, True)

    right_x = canvas.w - 1 - text_width(right)
    canvas.put(right_x, y, right, theme.dim)


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
                color_done: Color, color_todo: Color, theme: Theme,
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
        segments.append(("…", theme.dim2, False))
    if done:
        segments.append((done, color_done, bold_done))
    if todo:
        segments.append((todo, color_todo, False))
    if suffix:
        segments.append(("…", theme.dim2, False))

    total = _segments_width(segments)
    x = max(1, (canvas.w - total) // 2)
    draw_segments(canvas, x, y, segments, total)


def _draw_lyrics(canvas: Canvas, frame: Frame, theme: Theme,
                 prev_y: int, cur_y: int, next_y: int) -> None:
    lyrics = frame.lyrics
    if not lyrics or not lyrics.lines:
        hint = "no lyrics · add a .lrc or run fetch-lyrics.bat"
        hint = fit_text(hint, canvas.w - 2)
        x = max(1, (canvas.w - text_width(hint)) // 2)
        canvas.put(x, cur_y, hint, theme.dim)
        return

    t = frame.lyric_time
    index = lyrics.index_at(t)
    lines = lyrics.lines

    if index < 0:
        canvas.put(max(1, canvas.w // 2 - 1), cur_y, "♪", theme.accent_dim)
        next_text = lines[0].text
        _draw_lyric(canvas, next_y, next_text, 0.0,
                    theme.lyric_context, theme.lyric_context, theme)
        return

    current = lines[index]
    progress = lyrics.progress(index, t)
    _draw_lyric(canvas, cur_y, current.text, progress,
                theme.white, theme.lyric_todo, theme)

    if index > 0:
        _draw_lyric(canvas, prev_y, lines[index - 1].text, 1.0,
                    theme.lyric_context, theme.lyric_context, theme, False)
    if index + 1 < len(lines):
        _draw_lyric(canvas, next_y, lines[index + 1].text, 0.0,
                    theme.lyric_context, theme.lyric_context, theme, False)


def _draw_footer(canvas: Canvas, frame: Frame, theme: Theme) -> None:
    y = canvas.h - 1
    right = f"vol {int(round(frame.volume * 100))}%"
    if abs(frame.lyric_offset) >= 0.05:
        right = f"sync {frame.lyric_offset:+.1f}s · {right}"
    right_width = text_width(right)
    show_right = canvas.w >= 56
    limit = canvas.w - (right_width + 3 if show_right else 2)

    if frame.status:
        canvas.put(1, y, fit_text(frame.status, limit), theme.warn)
    else:
        hints = _FULL_HINT if _segments_width(
            [(key, theme.accent, True) for key, _ in _FULL_HINT]
        ) + sum(text_width(label) for _, label in _FULL_HINT) <= limit else _SHORT_HINT

        x = 1
        for key, label in hints:
            if x >= limit:
                break
            x = canvas.put(x, y, key,
                           theme.accent if frame.playing else theme.dim, True)
            x = canvas.put(x, y, label, theme.dim)

    if show_right:
        canvas.put(canvas.w - 1 - right_width, y, right, theme.dim2)


# -------------------------------------------------------------------- menu
def _draw_theme_menu(canvas: Canvas, theme: Theme, selected: int) -> None:
    themes = list(THEMES.values())
    selected = max(0, min(len(themes) - 1, int(selected)))
    box_w = min(46, max(20, canvas.w - 4))
    rows = min(len(themes), max(2, canvas.h - 6))
    box_h = rows + 4
    x = max(0, (canvas.w - box_w) // 2)
    y = max(0, (canvas.h - box_h) // 2)

    canvas.rect(x, y, x + box_w, y + box_h)
    canvas.put(x, y, "┌" + "─" * (box_w - 2) + "┐", theme.accent_dim)
    for row in range(y + 1, y + box_h - 1):
        canvas.put(x, row, "│", theme.accent_dim)
        canvas.put(x + box_w - 1, row, "│", theme.accent_dim)
    canvas.put(x, y + box_h - 1, "└" + "─" * (box_w - 2) + "┘",
               theme.accent_dim)

    canvas.put(x + 2, y + 1, "COLOR THEME", theme.accent, True)
    start = max(0, min(selected - rows // 2, len(themes) - rows))
    if rows < len(themes) and box_w >= 30:
        counter = f"{start + 1}-{start + rows}/{len(themes)}"
        canvas.put(x + box_w - 2 - text_width(counter), y + 1,
                   counter, theme.dim2)

    name_x = x + 3
    compact = box_w < 38
    name_w = box_w - 5 if compact else 11
    sw_x = name_x + name_w + 2
    sw_w = 0 if compact else max(4, min(14, x + box_w - 8 - sw_x))
    for i in range(start, start + rows):
        preset = themes[i]
        row_y = y + 2 + (i - start)
        is_selected = i == selected
        if is_selected:
            canvas.put(x + 1, row_y, "▌", theme.accent, True)
        canvas.put(name_x, row_y, fit_text(preset.label, name_w),
                   preset.white if is_selected else preset.dim, is_selected)
        if sw_w:
            for k in range(sw_w):
                level = k / max(1, sw_w - 1)
                canvas.put(sw_x + k, row_y, "█", preset.eq_color(level))
            sample_x = sw_x + sw_w + 2
            if sample_x + 1 < x + box_w - 2:
                canvas.put(sample_x, row_y, "A", preset.white, True)
                canvas.put(sample_x + 1, row_y, "a", preset.accent)

    footer_y = y + box_h - 2
    if box_w >= 42:
        segments = [
            ("↑↓", theme.accent, True), (" preview   ", theme.dim, False),
            ("Enter", theme.accent, True), (" apply   ", theme.dim, False),
            ("Esc", theme.accent, True), (" cancel", theme.dim, False),
        ]
    else:
        segments = [
            ("↑↓", theme.accent, True), (" · ", theme.dim, False),
            ("Enter", theme.accent, True), (" · ", theme.dim, False),
            ("Esc", theme.accent, True),
        ]
    draw_segments(canvas, x + 2, footer_y, segments, box_w - 4)


def _draw_playlist(canvas: Canvas, theme: Theme, view: PlaylistView) -> None:
    rows = view.rows
    if not rows:
        return
    total = len(rows)
    selected = max(0, min(total - 1, int(view.selected)))
    box_w = min(80, max(24, canvas.w - 4))
    items = min(6, max(1, (canvas.h - 8) // 4), total)
    box_h = items * 4 + 4
    x = max(0, (canvas.w - box_w) // 2)
    y = max(0, (canvas.h - box_h) // 2)

    canvas.rect(x, y, x + box_w, y + box_h)
    canvas.put(x, y, "┌" + "─" * (box_w - 2) + "┐", theme.accent_dim)
    for row in range(y + 1, y + box_h - 1):
        canvas.put(x, row, "│", theme.accent_dim)
        canvas.put(x + box_w - 1, row, "│", theme.accent_dim)
    canvas.put(x, y + box_h - 1, "└" + "─" * (box_w - 2) + "┘",
               theme.accent_dim)

    canvas.put(x + 2, y + 1, "PLAYLIST", theme.accent, True)
    counter = f"{total} track" if total == 1 else f"{total} tracks"
    if text_width(counter) + 16 < box_w:
        canvas.put(x + box_w - 3 - text_width(counter), y + 1,
                   counter, theme.dim2)

    start = max(0, min(selected - items // 2, total - items))
    compact = box_w < 60
    text_x = x + 5 if compact else x + 12
    for slot in range(items):
        row_index = start + slot
        item = rows[row_index]
        item_y = y + 2 + slot * 4
        is_selected = row_index == selected
        is_current = item.current or item.index == view.current

        if is_selected:
            for dy in range(3):
                canvas.put(x + 1, item_y + dy, "▌", theme.accent)

        if not compact:
            cover_x = x + 2
            if item.cover:
                for cy in range(3):
                    for cx in range(8):
                        color = item.cover[cy][cx]
                        canvas.put(cover_x + cx, item_y + cy, " ",
                                   bg=color)
            else:
                for cy in range(3):
                    for cx in range(8):
                        level = 0.15 + 0.75 * (
                            (item.index * 3 + cx + cy * 2) % 9
                        ) / 8.0
                        color = theme.eq_color(level)
                        canvas.put(cover_x + cx, item_y + cy, " ",
                                   bg=mix(theme.dim2, color, 0.75))

        marker = "▶" if is_current else " "
        canvas.put(text_x - 2, item_y, marker,
                   theme.accent if is_current else theme.dim)
        title_color = (theme.accent if is_current
                       else theme.white if is_selected else theme.text)
        duration = fmt_time(item.duration) if item.duration else ""
        duration_x = x + box_w - 3 - text_width(duration)
        title_width = max(4, duration_x - text_x - 2)
        canvas.put(text_x, item_y, fit_text(item.title, title_width),
                   title_color, is_current or is_selected)
        if duration:
            canvas.put(duration_x, item_y, duration, theme.dim2)

        artist = item.artist or "unknown artist"
        if item.album:
            artist = f"{artist} · {item.album}"
        meta_width = max(4, x + box_w - 3 - text_x)
        canvas.put(text_x, item_y + 1, fit_text(artist, meta_width),
                   theme.dim)
        meta = f"{item.index + 1:02d} / {total}"
        canvas.put(text_x, item_y + 2, fit_text(meta, meta_width),
                   theme.dim2)

    footer_y = y + box_h - 2
    if box_w >= 52:
        segments = [
            ("↑↓", theme.accent, True), (" select   ", theme.dim, False),
            ("Enter", theme.accent, True), (" play   ", theme.dim, False),
            ("Esc", theme.accent, True), (" close", theme.dim, False),
        ]
    else:
        segments = [
            ("↑↓", theme.accent, True), (" · ", theme.dim, False),
            ("Enter", theme.accent, True), (" · ", theme.dim, False),
            ("Esc", theme.accent, True),
        ]
    draw_segments(canvas, x + 2, footer_y, segments, box_w - 4)


def _draw_eq_menu(canvas: Canvas, theme: Theme, selected: int,
                  presets=None) -> None:
    presets = tuple(presets) if presets else EQ_LIST
    selected = max(0, min(len(presets) - 1, int(selected)))
    box_w = min(64, max(26, canvas.w - 4))
    rows = min(len(presets), max(2, canvas.h - 4))
    box_h = rows + 4
    x = max(0, (canvas.w - box_w) // 2)
    y = max(0, (canvas.h - box_h) // 2)

    canvas.rect(x, y, x + box_w, y + box_h)
    canvas.put(x, y, "┌" + "─" * (box_w - 2) + "┐", theme.accent_dim)
    for row in range(y + 1, y + box_h - 1):
        canvas.put(x, row, "│", theme.accent_dim)
        canvas.put(x + box_w - 1, row, "│", theme.accent_dim)
    canvas.put(x, y + box_h - 1, "└" + "─" * (box_w - 2) + "┘",
               theme.accent_dim)

    canvas.put(x + 2, y + 1, "SOUND PRESET", theme.accent, True)
    start = max(0, min(selected - rows // 2, len(presets) - rows))
    name_x = x + 3
    desc_x = name_x + 14
    for slot in range(rows):
        index = start + slot
        preset = presets[index]
        row_y = y + 2 + slot
        is_selected = index == selected
        if is_selected:
            canvas.put(x + 1, row_y, "▌", theme.accent, True)
        canvas.put(name_x, row_y, fit_text(preset.label, 13),
                   theme.white if is_selected else theme.dim,
                   is_selected)
        canvas.put(desc_x, row_y,
                   fit_text(preset.description, x + box_w - 3 - desc_x),
                   theme.text if is_selected else theme.dim2)

    footer_y = y + box_h - 2
    if box_w >= 56:
        segments = [
            ("↑↓", theme.accent, True), (" listen  ", theme.dim, False),
            ("Enter", theme.accent, True), (" apply  ", theme.dim, False),
            ("M", theme.accent, True), (" edit  ", theme.dim, False),
            ("Esc", theme.accent, True), (" cancel", theme.dim, False),
        ]
    elif box_w >= 44:
        segments = [
            ("↑↓", theme.accent, True), (" listen  ", theme.dim, False),
            ("Enter", theme.accent, True), (" apply  ", theme.dim, False),
            ("Esc", theme.accent, True), (" cancel", theme.dim, False),
        ]
    else:
        segments = [
            ("↑↓", theme.accent, True), (" · ", theme.dim, False),
            ("Enter", theme.accent, True), (" · ", theme.dim, False),
            ("Esc", theme.accent, True),
        ]
    draw_segments(canvas, x + 2, footer_y, segments, box_w - 4)


def _dialog_box(canvas: Canvas, theme: Theme, x: int, y: int,
                box_w: int, box_h: int) -> None:
    canvas.rect(x, y, x + box_w, y + box_h)
    canvas.put(x, y, "┌" + "─" * (box_w - 2) + "┐", theme.accent_dim)
    for row in range(y + 1, y + box_h - 1):
        canvas.put(x, row, "│", theme.accent_dim)
        canvas.put(x + box_w - 1, row, "│", theme.accent_dim)
    canvas.put(x, y + box_h - 1, "└" + "─" * (box_w - 2) + "┘",
               theme.accent_dim)


def _eq_editor_footer(canvas: Canvas, theme: Theme, x: int, y: int,
                      box_w: int) -> None:
    if box_w >= 75:
        segments = [
            ("↑↓", theme.accent, True), (" band  ", theme.dim, False),
            ("←→", theme.accent, True), (" ±0.5  ", theme.dim, False),
            ("PgUp/PgDn", theme.accent, True), (" ±3  ", theme.dim, False),
            ("0", theme.accent, True), (" reset  ", theme.dim, False),
            ("R", theme.accent, True), (" all  ", theme.dim, False),
            ("Enter", theme.accent, True), (" save  ", theme.dim, False),
            ("Esc", theme.accent, True), (" cancel", theme.dim, False),
        ]
    elif box_w >= 54:
        segments = [
            ("↑↓", theme.accent, True), (" band  ", theme.dim, False),
            ("←→", theme.accent, True), (" ±0.5  ", theme.dim, False),
            ("0", theme.accent, True), (" reset  ", theme.dim, False),
            ("Enter", theme.accent, True), (" save  ", theme.dim, False),
            ("Esc", theme.accent, True), (" cancel", theme.dim, False),
        ]
    elif box_w >= 30:
        segments = [
            ("↑↓", theme.accent, True), (" · ", theme.dim, False),
            ("←→", theme.accent, True), (" · ", theme.dim, False),
            ("Enter", theme.accent, True), (" save  ", theme.dim, False),
            ("Esc", theme.accent, True),
        ]
    else:
        segments = [
            ("↑↓", theme.accent, True), (" ", theme.dim, False),
            ("←→", theme.accent, True), (" ", theme.dim, False),
            ("Enter", theme.accent, True), (" ", theme.dim, False),
            ("Esc", theme.accent, True),
        ]
    draw_segments(canvas, x + 2, y, segments, box_w - 4)


def _draw_eq_editor_vertical(canvas: Canvas, theme: Theme,
                             gains: list[float], selected: int,
                             box_w: int) -> None:
    rows = 9
    box_h = rows + 8
    x = max(0, (canvas.w - box_w) // 2)
    y = max(0, (canvas.h - box_h) // 2)
    _dialog_box(canvas, theme, x, y, box_w, box_h)

    canvas.put(x + 2, y + 1, "CUSTOM EQUALIZER", theme.accent, True)
    preamp = -max(0.0, max(gains)) * 0.5
    right = f"preamp {preamp:.1f} dB"
    if box_w >= text_width("CUSTOM EQUALIZER") + text_width(right) + 8:
        canvas.put(x + box_w - 2 - text_width(right), y + 1, right,
                   theme.dim2)

    plot_x = x + 8
    plot_right = x + box_w - 2
    plot_w = plot_right - plot_x
    slot = max(2, plot_w // len(gains))
    offset = plot_x + max(0, (plot_w - slot * len(gains)) // 2)
    zero = (rows - 1) // 2

    for label, row in (("+12", 0), ("+6", 2), ("0", 4),
                       ("-6", 6), ("-12", 8)):
        canvas.put(x + 2 + (4 - text_width(label)), y + 3 + row,
                   label, theme.dim2)
    canvas.hline(y + 3 + zero, plot_x, plot_right, "─", theme.dim2)

    for i, value in enumerate(gains):
        col_x = offset + i * slot
        bar_w = 2 if slot >= 3 else 1
        bar_x = col_x + max(0, (slot - bar_w) // 2)
        level = int(round((MAX_GAIN - value) / (2 * MAX_GAIN) * (rows - 1)))
        level = max(0, min(rows - 1, level))
        if value > 0.04 and level >= zero:
            level = max(0, zero - 1)
        elif value < -0.04 and level <= zero:
            level = min(rows - 1, zero + 1)
        top, bottom = sorted((level, zero))
        is_selected = i == selected
        if value >= 0:
            color = theme.eq_color(0.5 + 0.5 * value / MAX_GAIN)
        else:
            color = mix(theme.dim2, theme.accent_dim, 0.6)
        if is_selected:
            color = theme.accent
        for row in range(top, bottom + 1):
            canvas.put(bar_x, y + 3 + row, "█" * bar_w, color,
                       is_selected)

        label = fit_text(_band_label(i), slot)
        label_x = col_x + max(0, (slot - text_width(label)) // 2)
        canvas.put(label_x, y + 12, label,
                   theme.accent if is_selected else theme.dim)

        text = _fmt_gain(value)
        if text_width(text) > slot:
            text = _fmt_gain(float(round(value)))
        text_x = col_x + max(0, (slot - text_width(text)) // 2)
        canvas.put(text_x, y + 13, text,
                   theme.white if is_selected else theme.dim2, is_selected)

    _eq_editor_footer(canvas, theme, x, y + box_h - 2, box_w)


def _draw_eq_editor_compact(canvas: Canvas, theme: Theme,
                            gains: list[float], selected: int,
                            box_w: int) -> None:
    total = len(gains)
    rows = min(total, max(2, canvas.h - 4))
    box_h = rows + 4
    x = max(0, (canvas.w - box_w) // 2)
    y = max(0, (canvas.h - box_h) // 2)
    _dialog_box(canvas, theme, x, y, box_w, box_h)

    canvas.put(x + 2, y + 1, fit_text("CUSTOM EQUALIZER", box_w - 4),
               theme.accent, True)
    preamp = -max(0.0, max(gains)) * 0.5
    right = f"preamp {preamp:.1f} dB"
    if box_w >= 46:
        canvas.put(x + box_w - 2 - text_width(right), y + 1, right,
                   theme.dim2)

    start = max(0, min(selected - rows // 2, total - rows))
    meter_x = x + 8
    gain_w = 5
    meter_right = x + box_w - 3 - gain_w
    meter_w = max(3, meter_right - meter_x)
    gain_x = x + box_w - 2 - gain_w

    for slot in range(rows):
        i = start + slot
        value = gains[i]
        row_y = y + 2 + slot
        is_selected = i == selected
        if is_selected:
            canvas.put(x + 1, row_y, "▌", theme.accent, True)
        canvas.put(x + 3, row_y, fit_text(_band_label(i), 4),
                   theme.white if is_selected else theme.text, is_selected)

        center = meter_x + meter_w // 2
        half = max(1, min(center - meter_x,
                          meter_x + meter_w - 1 - center))
        steps = int(round(abs(value) / MAX_GAIN * half))
        if abs(value) > 0.04:
            steps = max(1, steps)
        if value >= 0:
            bar_color = (theme.eq_color(0.55 + 0.25 * value / MAX_GAIN)
                         if not is_selected else theme.accent)
        else:
            bar_color = (theme.accent if is_selected
                         else mix(theme.dim2, theme.accent_dim, 0.6))
        for k in range(meter_x, meter_x + meter_w):
            canvas.put(k, row_y, "─", theme.dim2)
        canvas.put(center, row_y, "┼", theme.dim2)
        direction = 1 if value >= 0 else -1
        for k in range(1, steps + 1):
            canvas.put(center + direction * k, row_y, "█", bar_color,
                       is_selected)

        text = _fmt_gain(value)
        canvas.put(gain_x + gain_w - text_width(text), row_y, text,
                   theme.white if is_selected else theme.dim2, is_selected)

    _eq_editor_footer(canvas, theme, x, y + box_h - 2, box_w)


def _draw_eq_editor(canvas: Canvas, theme: Theme,
                    view: EQEditorView) -> None:
    gains = list(clamp_gains(view.gains))
    selected = max(0, min(len(gains) - 1, int(view.band)))
    box_w = min(78, max(24, canvas.w - 4))
    if canvas.h >= 18 and canvas.w >= 58 and box_w >= 54:
        _draw_eq_editor_vertical(canvas, theme, gains, selected, box_w)
    else:
        _draw_eq_editor_compact(canvas, theme, gains, selected, box_w)


# -------------------------------------------------------------------- public
def render(frame: Frame, width: int, height: int,
           theme: Theme | str | None = None,
           menu: int | None = None,
           playlist: PlaylistView | None = None,
           eq_menu: int | None = None,
           eq_presets=None,
           eq_editor: EQEditorView | None = None) -> list[str]:
    if isinstance(theme, str):
        theme = get_theme(theme)
    if theme is None:
        theme = get_theme(DEFAULT_THEME)

    if width < 24 or height < 8:
        message = "terminal too small"
        canvas = Canvas(max(width, 1), max(height, 1))
        canvas.put(0, 0, message[:width], theme.dim)
        return canvas.to_lines()

    canvas = Canvas(width, height)

    if height < 14:
        _draw_header(canvas, frame, theme)
        canvas.hline(1, 1, width - 1, "─", theme.dim2)
        eq_bottom = height - 8
        if eq_bottom >= 2:
            _draw_eq(canvas, frame, theme, 2, eq_bottom)
        _draw_timeline(canvas, frame, theme, height - 6)
        _draw_lyrics(canvas, frame, theme, height - 5, height - 4, height - 3)
        _draw_footer(canvas, frame, theme)
    else:
        lyric_next = height - 3
        lyric_cur = height - 4
        lyric_prev = height - 5
        timeline_y = height - 7
        eq_bottom = timeline_y - 2
        eq_height = min(24, height - 11)
        eq_top = eq_bottom - eq_height + 1

        _draw_header(canvas, frame, theme)
        canvas.hline(1, 1, width - 1, "─", theme.dim2)
        _draw_eq(canvas, frame, theme, eq_top, eq_bottom)
        _draw_timeline(canvas, frame, theme, timeline_y)
        _draw_lyrics(canvas, frame, theme, lyric_prev, lyric_cur, lyric_next)
        _draw_footer(canvas, frame, theme)

    if menu is not None:
        canvas.dim(0.35)
        _draw_theme_menu(canvas, theme, menu)
    elif playlist is not None:
        canvas.dim(0.35)
        _draw_playlist(canvas, theme, playlist)
    elif eq_menu is not None:
        canvas.dim(0.35)
        _draw_eq_menu(canvas, theme, eq_menu, eq_presets)
    elif eq_editor is not None:
        canvas.dim(0.35)
        _draw_eq_editor(canvas, theme, eq_editor)

    return canvas.to_lines()
