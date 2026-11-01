import os
import subprocess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_version():
    try:
        with open(os.path.join(_ROOT, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip() or '0.0.0'
    except OSError:
        return '0.0.0'


def _read_commit():
    # Vercel exposes the deployed commit; locally fall back to git.
    sha = os.environ.get('VERCEL_GIT_COMMIT_SHA')
    if sha:
        return sha[:7]
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=_ROOT, capture_output=True, text=True, timeout=2,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


APP_VERSION = _read_version()
APP_COMMIT = _read_commit()
# Changes on every deploy so browsers refetch CSS/JS instead of using a stale copy.
ASSET_VERSION = f'{APP_VERSION}-{APP_COMMIT}' if APP_COMMIT else APP_VERSION
