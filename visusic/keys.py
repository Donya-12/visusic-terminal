"""Non-blocking keyboard input (Windows console)."""

from __future__ import annotations

import os

_ARROWS = {
    "H": "up",
    "P": "down",
    "K": "left",
    "M": "right",
    "G": "home",
    "O": "end",
}


class KeyReader:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("VisuSic Terminal currently supports Windows only")
        import msvcrt

        self._msvcrt = msvcrt

    def read(self) -> list[str]:
        keys: list[str] = []
        while self._msvcrt.kbhit():
            char = self._msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                code = self._msvcrt.getwch()
                key = _ARROWS.get(code)
                if key:
                    keys.append(key)
                continue
            if char == "\x03":
                keys.append("ctrl-c")
            elif char == "\x1b":
                keys.append("esc")
            elif char in ("\r", "\n"):
                keys.append("enter")
            elif char == " ":
                keys.append("space")
            elif char.isprintable():
                keys.append(char.lower())
        return keys
