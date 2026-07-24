"""core/paths.py -- Filesystem locations that differ between running from
source and running as a PyInstaller-frozen exe.
"""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory for user-writable files (config.yaml): next to the exe
    when frozen, the project root (cwd) otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def resource_dir() -> Path:
    """Base directory for bundled read-only resources (web/static,
    web/templates, Images/): PyInstaller's extraction directory when
    frozen, the project root otherwise."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent
