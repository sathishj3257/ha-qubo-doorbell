"""Snapshot history: dated photo folders under Home Assistant's media directory, with a size cap."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import re

from homeassistant.core import HomeAssistant

FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
IMAGE_EXT = (".jpg", ".jpeg", ".png")


def valid_folder(name: str) -> bool:
    """Single folder name only: no slashes, no '..', no leading dot."""
    return bool(FOLDER_RE.match(name)) and ".." not in name


def media_root(hass: HomeAssistant) -> str:
    dirs = hass.config.media_dirs or {}
    return dirs.get("local") or next(iter(dirs.values()), None) or hass.config.path("media")


@dataclass
class HistoryStats:
    count: int
    size_bytes: int
    oldest: float | None
    newest: float | None
    deleted: int = 0


def _files(base: str) -> list[tuple[float, int, str]]:
    out: list[tuple[float, int, str]] = []
    if not os.path.isdir(base):
        return out
    for root, _dirs, names in os.walk(base):
        for n in names:
            if n.lower().endswith(IMAGE_EXT):
                p = os.path.join(root, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append((st.st_mtime, st.st_size, p))
    out.sort()
    return out


def _remove_empty_dirs(base: str) -> None:
    for root, dirs, files in os.walk(base, topdown=False):
        if root != base and not dirs and not files:
            try:
                os.rmdir(root)
            except OSError:
                pass


def scan(base: str) -> HistoryStats:
    files = _files(base)
    return HistoryStats(
        count=len(files),
        size_bytes=sum(f[1] for f in files),
        oldest=files[0][0] if files else None,
        newest=files[-1][0] if files else None,
    )


def save_and_prune(base: str, data: bytes, ext: str, kind: str, when: datetime, max_bytes: int) -> tuple[str, HistoryStats]:
    """Write one photo into base/YYYY-MM-DD/HH-MM-SS <kind>.<ext>, then delete oldest photos over the cap."""
    day_dir = os.path.join(base, when.strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    stem = f"{when.strftime('%H-%M-%S')} {kind}"
    path = os.path.join(day_dir, f"{stem}.{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(day_dir, f"{stem} ({n}).{ext}")
        n += 1
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)

    files = _files(base)
    total = sum(f[1] for f in files)
    deleted = 0
    while files and total > max_bytes and len(files) > 1:
        _mtime, size, p = files.pop(0)
        if p == path:
            continue
        try:
            os.remove(p)
            total -= size
            deleted += 1
        except OSError:
            pass
    if deleted:
        _remove_empty_dirs(base)
    stats = scan(base)
    stats.deleted = deleted
    return path, stats
