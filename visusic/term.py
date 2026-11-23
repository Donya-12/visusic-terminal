"""Console setup, size and title helpers for Windows terminals."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from ctypes import wintypes

_STD_OUTPUT_HANDLE = -11
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_ALT_SCREEN = "\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H"
_NORMAL_SCREEN = "\x1b[0m\x1b[?25h\x1b[?1049l"

_kernel32 = None
if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetStdHandle.restype = wintypes.HANDLE
    _kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    _kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE,
                                        ctypes.POINTER(wintypes.DWORD)]
    _kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]


def write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _enable_vt() -> None:
    if _kernel32 is None:
        return
    handle = _kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
    mode = wintypes.DWORD()
    if _kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        _kernel32.SetConsoleMode(
            handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
        )


def size() -> tuple[int, int]:
    try:
        columns, lines = shutil.get_terminal_size(fallback=(100, 30))
    except OSError:
        columns, lines = 100, 30
    return max(1, columns - 1), max(1, lines)


def set_title(text: str) -> None:
    if _kernel32 is not None:
        try:
            _kernel32.SetConsoleTitleW(text)
        except Exception:
            pass


def setup() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    _enable_vt()
    write(_ALT_SCREEN)
    set_title("VisuSic Terminal")


def teardown() -> None:
    write(_NORMAL_SCREEN)
