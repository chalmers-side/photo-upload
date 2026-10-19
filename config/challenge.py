"""Load config/challenge-setting.yaml (re-read when the file changes)."""
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("challenge-setting.yaml")
_cache = None
_mtime = None


def settings():
    global _cache, _mtime
    mtime = _PATH.stat().st_mtime
    if _cache is None or mtime != _mtime:
        with _PATH.open(encoding="utf-8") as f:
            _cache = yaml.safe_load(f)
        _mtime = mtime
    return _cache
