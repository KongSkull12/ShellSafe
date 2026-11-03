"""Compile shellsafev2.ino into firmware/build/ for the dashboard flasher.

Usage:  python build_firmware.py

Needs arduino-cli (on PATH, or the copy bundled with Arduino IDE 2) with the
esp32 core installed, and a filled-in secrets.h next to the sketch. The
binaries contain those secrets, so firmware/build/ is gitignored and only
served to signed-in admins.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKETCH = ROOT / 'shellsafev2.ino'
SECRETS = ROOT / 'secrets.h'
OUT_DIR = ROOT / 'firmware' / 'build'
FQBN = 'esp32:esp32:esp32wrover'

IDE_CLI_PATHS = [
    Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
    / 'Arduino IDE' / 'resources' / 'app' / 'lib' / 'backend' / 'resources' / 'arduino-cli.exe',
    Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Arduino IDE'
    / 'resources' / 'app' / 'lib' / 'backend' / 'resources' / 'arduino-cli.exe',
    Path('/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli'),
]


def find_cli():
    found = shutil.which('arduino-cli')
    if found:
        return found
    for path in IDE_CLI_PATHS:
        if path.is_file():
            return str(path)
    sys.exit('arduino-cli not found. Install it or Arduino IDE 2, then try again.')


def firmware_label():
    match = re.search(r'Firmware:\s*([^"#]+?)\s*#?"', SKETCH.read_text(encoding='utf-8'))
    return match.group(1).strip() if match else 'unknown'


def git_commit():
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ''


def main():
    if not SECRETS.is_file():
        sys.exit('secrets.h is missing. Copy secrets.h.example to secrets.h and fill it in.')
    cli = find_cli()

    # arduino-cli needs the folder name to match the .ino name.
    with tempfile.TemporaryDirectory() as tmp:
        sketch_dir = Path(tmp) / SKETCH.stem
        sketch_dir.mkdir()
        shutil.copy2(SKETCH, sketch_dir)
        shutil.copy2(SECRETS, sketch_dir)

        if OUT_DIR.exists():
            shutil.rmtree(OUT_DIR)
        OUT_DIR.mkdir(parents=True)
        print(f'Compiling {SKETCH.name} for {FQBN}...', flush=True)
        result = subprocess.run(
            [cli, 'compile', '--fqbn', FQBN, '--output-dir', str(OUT_DIR), str(sketch_dir)]
        )
        if result.returncode != 0:
            sys.exit('Compile failed.')

    app_bin = OUT_DIR / f'{SKETCH.name}.bin'
    merged_bin = OUT_DIR / f'{SKETCH.name}.merged.bin'
    info = {
        'firmware': firmware_label(),
        'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'commit': git_commit(),
        'fqbn': FQBN,
        'app_size': app_bin.stat().st_size,
        'has_full': merged_bin.is_file(),
    }
    (OUT_DIR / 'build.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    print(f"Built firmware {info['firmware']} ({info['app_size']:,} bytes) in {OUT_DIR}")
    print('Open Settings > Firmware in the dashboard to flash it.')


if __name__ == '__main__':
    main()
