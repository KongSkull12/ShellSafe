"""Locally compiled firmware (from build_firmware.py) offered on the flasher page.

The binaries embed secrets.h, so they live in gitignored firmware/build/ and
are only ever served to admins. Deployed servers have no build and the page
falls back to picking a .bin file from the computer.
"""
import json
from datetime import datetime
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent.parent / 'firmware' / 'build'
BUILD_FILES = {
    'app': 'shellsafev2.ino.bin',
    'full': 'shellsafev2.ino.merged.bin',
}


def latest_build():
    """Return build.json details if an app binary is present, else None."""
    if not (BUILD_DIR / BUILD_FILES['app']).is_file():
        return None
    try:
        info = json.loads((BUILD_DIR / 'build.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        info = {}
    info['has_full'] = (BUILD_DIR / BUILD_FILES['full']).is_file()
    try:
        info['built_at'] = datetime.fromisoformat(info['built_at'])
    except (KeyError, TypeError, ValueError):
        info['built_at'] = None
    return info


def build_file(kind):
    name = BUILD_FILES.get(kind)
    if not name:
        return None
    path = BUILD_DIR / name
    return path if path.is_file() else None
