"""Color themes and persistence for VisuSic Terminal."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

Color = tuple[int, int, int]

DEFAULT_THEME = "aurora"


def mix(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    accent: Color
    accent_dim: Color
    white: Color
    text: Color
    dim: Color
    dim2: Color
    warn: Color
    lyric_todo: Color
    lyric_context: Color
    eq_stops: tuple[tuple[float, Color], ...]

    def eq_color(self, level: float) -> Color:
        level = max(0.0, min(1.0, level))
        for index in range(1, len(self.eq_stops)):
            left_t, left_c = self.eq_stops[index - 1]
            right_t, right_c = self.eq_stops[index]
            if level <= right_t:
                span = right_t - left_t or 1.0
                return mix(left_c, right_c, (level - left_t) / span)
        return self.eq_stops[-1][1]


THEMES: dict[str, Theme] = {
    "aurora": Theme(
        name="aurora",
        label="Aurora",
        accent=(110, 240, 198),
        accent_dim=(66, 160, 138),
        white=(240, 246, 255),
        text=(196, 206, 222),
        dim=(104, 114, 132),
        dim2=(58, 64, 78),
        warn=(255, 194, 112),
        lyric_todo=(98, 108, 126),
        lyric_context=(86, 96, 114),
        eq_stops=(
            (0.00, (96, 74, 255)),
            (0.30, (66, 158, 255)),
            (0.58, (64, 232, 222)),
            (0.82, (150, 255, 202)),
            (1.00, (240, 255, 246)),
        ),
    ),
    "synthwave": Theme(
        name="synthwave",
        label="Synthwave",
        accent=(255, 92, 214),
        accent_dim=(176, 62, 166),
        white=(255, 241, 252),
        text=(224, 199, 228),
        dim=(150, 116, 166),
        dim2=(82, 56, 92),
        warn=(255, 196, 102),
        lyric_todo=(138, 103, 150),
        lyric_context=(116, 86, 128),
        eq_stops=(
            (0.00, (44, 16, 96)),
            (0.28, (124, 38, 210)),
            (0.55, (255, 62, 190)),
            (0.80, (255, 140, 92)),
            (1.00, (255, 236, 184)),
        ),
    ),
    "matrix": Theme(
        name="matrix",
        label="Matrix",
        accent=(80, 255, 140),
        accent_dim=(42, 160, 88),
        white=(224, 255, 232),
        text=(168, 226, 182),
        dim=(83, 150, 103),
        dim2=(34, 62, 44),
        warn=(255, 210, 90),
        lyric_todo=(90, 140, 104),
        lyric_context=(70, 112, 84),
        eq_stops=(
            (0.00, (6, 30, 14)),
            (0.30, (18, 110, 48)),
            (0.60, (46, 220, 104)),
            (0.82, (150, 255, 180)),
            (1.00, (236, 255, 240)),
        ),
    ),
    "ice": Theme(
        name="ice",
        label="Ice",
        accent=(104, 212, 255),
        accent_dim=(58, 132, 178),
        white=(234, 248, 255),
        text=(186, 214, 232),
        dim=(96, 126, 148),
        dim2=(46, 62, 78),
        warn=(255, 190, 120),
        lyric_todo=(100, 128, 148),
        lyric_context=(82, 106, 126),
        eq_stops=(
            (0.00, (20, 40, 120)),
            (0.30, (38, 120, 220)),
            (0.60, (76, 220, 255)),
            (0.82, (170, 248, 255)),
            (1.00, (244, 255, 255)),
        ),
    ),
    "amber": Theme(
        name="amber",
        label="Amber",
        accent=(255, 180, 84),
        accent_dim=(176, 112, 48),
        white=(255, 244, 220),
        text=(226, 204, 170),
        dim=(148, 120, 88),
        dim2=(78, 62, 44),
        warn=(255, 104, 88),
        lyric_todo=(140, 112, 80),
        lyric_context=(112, 90, 64),
        eq_stops=(
            (0.00, (64, 28, 8)),
            (0.30, (140, 64, 14)),
            (0.60, (255, 138, 36)),
            (0.82, (255, 206, 92)),
            (1.00, (255, 246, 204)),
        ),
    ),
    "mono": Theme(
        name="mono",
        label="Mono",
        accent=(225, 232, 242),
        accent_dim=(140, 150, 164),
        white=(250, 252, 255),
        text=(210, 216, 226),
        dim=(118, 126, 140),
        dim2=(58, 63, 73),
        warn=(255, 200, 120),
        lyric_todo=(110, 118, 132),
        lyric_context=(92, 100, 112),
        eq_stops=(
            (0.00, (42, 46, 54)),
            (0.35, (105, 112, 124)),
            (0.65, (168, 176, 188)),
            (0.85, (220, 226, 236)),
            (1.00, (255, 255, 255)),
        ),
    ),
}

THEME_LIST = tuple(THEMES.values())


def theme_names() -> list[str]:
    return list(THEMES)


def get_theme(name: str | None) -> Theme:
    if name and name in THEMES:
        return THEMES[name]
    return THEMES[DEFAULT_THEME]


def config_path() -> Path:
    override = os.environ.get("VISUSIC_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or
                    (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or
                    (Path.home() / ".config"))
    return base / "visusic-terminal" / "config.json"


def load_theme_name(path: Path | str | None = None) -> str:
    target = Path(path) if path is not None else config_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_THEME
    name = data.get("theme") if isinstance(data, dict) else None
    return name if name in THEMES else DEFAULT_THEME


def save_theme_name(name: str, path: Path | str | None = None) -> bool:
    if name not in THEMES:
        return False
    target = Path(path) if path is not None else config_path()
    temp = target.with_suffix(target.suffix + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps({"theme": name}, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        os.replace(temp, target)
        return True
    except OSError:
        try:
            temp.unlink()
        except OSError:
            pass
        return False
