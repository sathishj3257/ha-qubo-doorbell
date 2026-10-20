"""Snapshot history: dated photo/clip folders under Home Assistant's media directory, with size caps.

Photos and video clips share the dated folders but have separate size limits:
when either kind grows past its limit, its oldest files are deleted first.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import os
import re
import shutil

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HISTORY_ENABLED,
    CONF_HISTORY_FOLDER,
    CONF_HISTORY_MAX_MB,
    CONF_VIDEO_MAX_MB,
    DEFAULT_HISTORY_ENABLED,
    DEFAULT_HISTORY_FOLDER,
    DEFAULT_HISTORY_MAX_MB,
    DEFAULT_VIDEO_MAX_MB,
    SIGNAL_HISTORY,
)

_LOGGER = logging.getLogger(__name__)

FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
IMAGE_EXT = (".jpg", ".jpeg", ".png")
VIDEO_EXT = (".mp4",)


def valid_folder(name: str) -> bool:
    """Single folder name only: no slashes, no '..', no leading dot."""
    return bool(FOLDER_RE.match(name)) and ".." not in name


def media_root(hass: HomeAssistant) -> str:
    dirs = hass.config.media_dirs or {}
    return dirs.get("local") or next(iter(dirs.values()), None) or hass.config.path("media")


def history_base(hass: HomeAssistant, options: dict) -> str | None:
    """Absolute history folder for these options, or None if disabled / invalid."""
    if not options.get(CONF_HISTORY_ENABLED, DEFAULT_HISTORY_ENABLED):
        return None
    folder = options.get(CONF_HISTORY_FOLDER, DEFAULT_HISTORY_FOLDER)
    if not valid_folder(folder):
        _LOGGER.warning("Qubo history folder name %r is not allowed; skipping", folder)
        return None
    return os.path.join(media_root(hass), folder)


@dataclass
class HistoryStats:
    count: int
    size_bytes: int
    oldest: float | None
    newest: float | None
    deleted: int = 0


def _files(base: str, exts: tuple[str, ...]) -> list[tuple[float, int, str]]:
    out: list[tuple[float, int, str]] = []
    if not os.path.isdir(base):
        return out
    for root, _dirs, names in os.walk(base):
        for n in names:
            if n.lower().endswith(exts):
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


def scan(base: str, exts: tuple[str, ...] = IMAGE_EXT) -> HistoryStats:
    files = _files(base, exts)
    return HistoryStats(
        count=len(files),
        size_bytes=sum(f[1] for f in files),
        oldest=files[0][0] if files else None,
        newest=files[-1][0] if files else None,
    )


def _target(base: str, when: datetime, kind: str, ext: str) -> str:
    day_dir = os.path.join(base, when.strftime("%Y-%m-%d"))
    os.makedirs(day_dir, exist_ok=True)
    stem = f"{when.strftime('%H-%M-%S')} {kind}"
    path = os.path.join(day_dir, f"{stem}.{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(day_dir, f"{stem} ({n}).{ext}")
        n += 1
    return path


def _prune(base: str, keep: str, max_bytes: int, exts: tuple[str, ...]) -> HistoryStats:
    files = _files(base, exts)
    total = sum(f[1] for f in files)
    deleted = 0
    while files and total > max_bytes and len(files) > 1:
        _mtime, size, p = files.pop(0)
        if p == keep:
            continue
        try:
            os.remove(p)
            total -= size
            deleted += 1
        except OSError:
            pass
    if deleted:
        _remove_empty_dirs(base)
    stats = scan(base, exts)
    stats.deleted = deleted
    return stats


def save_and_prune(base: str, data: bytes, ext: str, kind: str, when: datetime, max_bytes: int) -> tuple[str, HistoryStats]:
    """Write one photo into base/YYYY-MM-DD/HH-MM-SS <kind>.<ext>, then delete oldest photos over the cap."""
    path = _target(base, when, kind, ext)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path, _prune(base, path, max_bytes, IMAGE_EXT)


def move_and_prune(base: str, src: str, kind: str, when: datetime, max_bytes: int) -> tuple[str, HistoryStats]:
    """Move a finished clip into base/YYYY-MM-DD/HH-MM-SS <kind>.mp4, then delete oldest clips over the cap."""
    path = _target(base, when, kind, "mp4")
    shutil.move(src, path)
    return path, _prune(base, path, max_bytes, VIDEO_EXT)


def scan_all(base: str) -> tuple[HistoryStats, HistoryStats]:
    return scan(base, IMAGE_EXT), scan(base, VIDEO_EXT)


async def async_save_to_history(
    hass: HomeAssistant, entry_id: str, data: bytes, ext: str, kind: str, when: datetime | None = None
) -> str | None:
    """Save one photo if history is enabled in the entry options; notify the history sensor."""
    entry = hass.config_entries.async_get_entry(entry_id)
    opts = entry.options if entry else {}
    base = history_base(hass, opts)
    if base is None:
        return None
    max_bytes = int(opts.get(CONF_HISTORY_MAX_MB, DEFAULT_HISTORY_MAX_MB)) * 1024 * 1024
    try:
        path, stats = await hass.async_add_executor_job(
            save_and_prune, base, data, ext, kind, when or dt_util.now(), max_bytes
        )
    except OSError as err:
        _LOGGER.warning("Could not save Qubo snapshot to history: %s", err)
        return None
    _LOGGER.info(
        "Saved %s to history (%d photos, %.1f MB, %d old deleted)",
        path, stats.count, stats.size_bytes / 1048576, stats.deleted,
    )
    async_dispatcher_send(hass, f"{SIGNAL_HISTORY}_{entry_id}")
    return path


async def async_save_clip_to_history(
    hass: HomeAssistant, entry_id: str, src: str, kind: str, when: datetime
) -> str | None:
    """Move a recorded clip into the history (separate size cap); notify the history sensor."""
    entry = hass.config_entries.async_get_entry(entry_id)
    opts = entry.options if entry else {}
    base = history_base(hass, opts)
    if base is None:
        return None
    max_bytes = int(opts.get(CONF_VIDEO_MAX_MB, DEFAULT_VIDEO_MAX_MB)) * 1024 * 1024
    try:
        path, stats = await hass.async_add_executor_job(move_and_prune, base, src, kind, when, max_bytes)
    except OSError as err:
        _LOGGER.warning("Could not save Qubo clip to history: %s", err)
        return None
    _LOGGER.info(
        "Saved %s to history (%d clips, %.1f MB, %d old deleted)",
        path, stats.count, stats.size_bytes / 1048576, stats.deleted,
    )
    async_dispatcher_send(hass, f"{SIGNAL_HISTORY}_{entry_id}")
    return path
