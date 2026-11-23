#!/usr/bin/env python3
"""Build standalone Windows executables with PyInstaller.

Install the optional build dependency first:
    .venv\\Scripts\\pip install -e .[build]
Then:
    .venv\\Scripts\\python tools\\build_exe.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"

TARGETS = {
    "visusic": {
        "module": "visusic.cli",
        "collect": ("sounddevice", "soundfile"),
    },
    "visusic-fetch": {
        "module": "visusic.fetch",
        "collect": ("soundfile",),
    },
}


def build(name: str, module: str, collect: tuple[str, ...]) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    entry = BUILD / f"_entry_{name.replace('-', '_')}.py"
    entry.write_text(
        f"from {module} import main\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", name,
        "--paths", str(ROOT),
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
    ]
    for package in collect:
        command += ["--collect-data", package]
    command.append(str(entry))

    print(f"\n=== {name} ===")
    subprocess.run(command, cwd=ROOT, check=True)
    return DIST / f"{name}.exe"


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:")
        print(r"  .venv\Scripts\pip install -e .[build]")
        return 1

    parser = argparse.ArgumentParser(description="Build VisuSic executables")
    parser.add_argument("targets", nargs="*", choices=sorted(TARGETS),
                        help="targets to build (default: all)")
    args = parser.parse_args()
    names = args.targets or list(TARGETS)

    for name in names:
        target = TARGETS[name]
        path = build(name, target["module"], target["collect"])
        print(f"Built {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
