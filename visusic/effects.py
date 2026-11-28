"""Animated background effects for the terminal visualizer.

Effects are drawn behind the interface and stay deliberately dim.  Some follow
the music (waves, stars, bubbles), others just set a mood (snow, rain).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .theme import Theme, mix


@dataclass(frozen=True)
class Effect:
    name: str
    label: str
    description: str
    reactive: bool = False


EFFECTS: dict[str, Effect] = {
    "none": Effect(
        "none", "None", "чистый фон без эффектов",
    ),
    "snow": Effect(
        "snow", "Snow", "снежинки медленно падают, не реагируют",
    ),
    "rain": Effect(
        "rain", "Rain", "частый дождь, не реагирует на музыку",
    ),
    "waves": Effect(
        "waves", "Waves", "волны внизу откликаются на бас", True,
    ),
    "stars": Effect(
        "stars", "Stars", "звёзды мерцают в такт музыке", True,
    ),
    "bubbles": Effect(
        "bubbles", "Bubbles", "пузырьки всплывают на бас", True,
    ),
}

EFFECT_LIST = tuple(EFFECTS.values())


def get_effect(name: str | None) -> Effect:
    if name and name in EFFECTS:
        return EFFECTS[name]
    return EFFECTS["none"]


def effect_names() -> list[str]:
    return list(EFFECTS)


class Background:
    """Particle/time based backdrop shared by the app and preview tools."""

    def __init__(self, name: str = "none", seed: int = 2026) -> None:
        self._rng = random.Random(seed)
        self._name = get_effect(name).name
        self._particles: list[list[float | str]] = []
        self._size = (0, 0)
        self._time = 0.0
        self._level = 0.0
        self._bass = 0.0

    @property
    def name(self) -> str:
        return self._name

    @property
    def effect(self) -> Effect:
        return get_effect(self._name)

    @property
    def reactive(self) -> bool:
        return self.effect.reactive

    def set_effect(self, name: str) -> None:
        effect = get_effect(name)
        if effect.name == self._name:
            return
        self._name = effect.name
        self._particles.clear()
        self._size = (0, 0)
        self._time = 0.0

    # ------------------------------------------------------------- lifecycle
    def update(self, dt: float, width: int, height: int, bars=None,
               playing: bool = True) -> None:
        dt = max(0.0, min(0.2, float(dt)))
        self._time += dt
        if self._name == "none" or width <= 0 or height <= 0:
            return
        if (width, height) != self._size:
            self._size = (width, height)
            self._spawn(width, height)

        if bars is not None and len(bars):
            values = [float(value) for value in bars]
            level = sum(values) / len(values)
            bass_count = max(1, len(values) // 4)
            bass = sum(values[:bass_count]) / bass_count
            if not playing:
                level *= 0.2
                bass *= 0.2
            rate = min(1.0, dt * 7.0)
            self._level += (level - self._level) * rate
            self._bass += (bass - self._bass) * rate
        else:
            decay = max(0.0, 1.0 - dt * 3.0)
            self._level *= decay
            self._bass *= decay

        if self._name == "snow":
            self._update_snow(dt, width, height)
        elif self._name == "rain":
            self._update_rain(dt, width, height)
        elif self._name == "stars":
            self._update_stars()
        elif self._name == "bubbles":
            self._update_bubbles(dt, width, height)

    def _spawn(self, width: int, height: int) -> None:
        self._particles = []
        self._rng.seed(9173 + width * 31 + height * 17)
        if self._name == "snow":
            count = max(18, width * height // 90)
            for _ in range(count):
                self._particles.append([
                    self._rng.uniform(0, width - 1),
                    self._rng.uniform(0, height - 1),
                    self._rng.uniform(1.2, 4.8),
                    self._rng.uniform(0, math.tau),
                    self._rng.choice(("*", "·", "+")),
                ])
        elif self._name == "rain":
            count = max(14, width // 2)
            for _ in range(count):
                self._particles.append([
                    self._rng.uniform(0, width - 1),
                    self._rng.uniform(0, height - 1),
                    self._rng.uniform(18.0, 36.0),
                    self._rng.choice((1.0, 2.0)),
                ])
        elif self._name == "stars":
            count = max(16, width * height // 130)
            for _ in range(count):
                self._particles.append([
                    self._rng.uniform(0, width - 1),
                    self._rng.uniform(1, height - 2),
                    self._rng.uniform(0, math.tau),
                    self._rng.uniform(0.6, 1.8),
                ])
        elif self._name == "bubbles":
            count = max(12, width // 8)
            for _ in range(count):
                self._particles.append([
                    self._rng.uniform(0, width - 1),
                    self._rng.uniform(0, height - 1),
                    self._rng.uniform(1.5, 4.0),
                    self._rng.uniform(0, math.tau),
                    self._rng.choice(("○", "◦", "·")),
                ])

    # --------------------------------------------------------------- motion
    def _update_snow(self, dt: float, width: int, height: int) -> None:
        for particle in self._particles:
            particle[1] = float(particle[1]) + float(particle[2]) * dt
            particle[0] = float(particle[0]) + math.sin(
                self._time * 0.8 + float(particle[3])
            ) * 1.1 * dt
            if float(particle[1]) >= height:
                particle[1] = -0.5
                particle[0] = self._rng.uniform(0, width - 1)
            particle[0] = min(max(0.0, float(particle[0])), width - 1)

    def _update_rain(self, dt: float, width: int, height: int) -> None:
        for particle in self._particles:
            particle[1] = float(particle[1]) + float(particle[2]) * dt
            if float(particle[1]) >= height:
                particle[1] = -float(particle[3])
                particle[0] = self._rng.uniform(0, width - 1)

    def _update_stars(self) -> None:
        # Stars are static; twinkling happens at draw time.
        return

    def _update_bubbles(self, dt: float, width: int,
                        height: int) -> None:
        speed_boost = 1.0 + self._bass * 5.0
        for particle in self._particles:
            particle[1] = float(particle[1]) - (
                float(particle[2]) * speed_boost * dt
            )
            particle[0] = float(particle[0]) + math.sin(
                self._time * 1.6 + float(particle[3])
            ) * 0.9 * dt
            if float(particle[1]) < 0:
                particle[1] = float(height)
                particle[0] = self._rng.uniform(0, width - 1)
            particle[0] = min(max(0.0, float(particle[0])), width - 1)

    # ---------------------------------------------------------------- drawing
    def draw(self, canvas, theme: Theme) -> None:
        if self._name == "none" or not self._particles \
                and self._name != "waves":
            return
        if self._name == "snow":
            color = mix(theme.white, theme.dim2, 0.74)
            for particle in self._particles:
                canvas.put(int(float(particle[0])), int(float(particle[1])),
                           str(particle[4]), color)
        elif self._name == "rain":
            color = mix(theme.accent_dim, theme.dim2, 0.55)
            for particle in self._particles:
                x = int(float(particle[0]))
                y = int(float(particle[1]))
                canvas.put(x, y, "│", color)
                if float(particle[3]) >= 2:
                    canvas.put(x, y - 1, "┆", mix(color, theme.dim2, 0.45))
        elif self._name == "stars":
            for particle in self._particles:
                twinkle = 0.5 + 0.5 * math.sin(
                    self._time * float(particle[3]) + float(particle[2])
                )
                glow = min(1.0, twinkle * 0.55 + self._level * 0.55)
                color = mix(theme.dim2, theme.accent, 0.25 + glow * 0.6)
                char = "*" if glow > 0.72 else "+" if glow > 0.38 else "·"
                canvas.put(int(float(particle[0])), int(float(particle[1])),
                           char, color, glow > 0.82)
        elif self._name == "bubbles":
            color = mix(theme.accent_dim, theme.dim2, 0.45)
            for particle in self._particles:
                canvas.put(int(float(particle[0])), int(float(particle[1])),
                           str(particle[4]), color)
        elif self._name == "waves":
            self._draw_waves(canvas, theme)

    def _draw_waves(self, canvas, theme: Theme) -> None:
        width = canvas.w
        height = canvas.h
        if width < 2 or height < 4:
            return
        base = max(3, height - 5)
        for wave in range(3):
            amplitude = 1.0 + self._bass * 4.0 + wave * 0.5
            level = 0.0 if wave == 2 else self._level
            phase = self._time * (0.9 + wave * 0.27) + wave * 1.9
            color = mix(
                theme.accent_dim, theme.dim2,
                0.45 + wave * 0.16 - level * 0.18,
            )
            for x in range(width):
                y = int(round(
                    base - wave * 2
                    + math.sin(x * 0.095 + phase) * amplitude
                    + math.sin(x * 0.031 - phase * 0.7) * amplitude * 0.5
                ))
                y = max(2, min(height - 4, y))
                canvas.put(x, y, "~" if wave != 1 else "≈", color)
