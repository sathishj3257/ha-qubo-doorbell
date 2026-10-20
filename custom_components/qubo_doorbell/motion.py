"""Motion photos.

Qubo motion/person alerts don't carry a downloadable photo (only a path on the
doorbell itself), so when one arrives this briefly opens the cloud live stream,
grabs a single frame with ffmpeg, closes the stream and saves the frame into the
snapshot history.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HISTORY_ENABLED,
    CONF_MOTION_COOLDOWN,
    CONF_MOTION_SNAPSHOTS,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_SECONDS,
    DEFAULT_HISTORY_ENABLED,
    DEFAULT_MOTION_COOLDOWN,
    DEFAULT_MOTION_SNAPSHOTS,
    DEFAULT_VIDEO_ENABLED,
    DEFAULT_VIDEO_SECONDS,
    DOMAIN,
    MOTION_CAUSES,
    RING_SNAPSHOT_WINDOW,
    VIEWER_GRACE,
)
from .history import async_save_clip_to_history, async_save_to_history

_LOGGER = logging.getLogger(__name__)
GRAB_TIMEOUT = 25
MAX_FRAME_BYTES = 5 * 1024 * 1024


def _redact(text: str) -> str:
    """Never log stream links (they carry access tokens)."""
    return re.sub(r"\w+://\S+", "<url>", text)


async def _grab_frame(url: str) -> bytes | None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", url,
        "-frames:v", "1", "-q:v", "4", "-update", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        data, err = await asyncio.wait_for(proc.communicate(), timeout=GRAB_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        _LOGGER.warning("Qubo motion photo: stream did not deliver a frame within %ss", GRAB_TIMEOUT)
        return None
    if proc.returncode != 0 or data[:3] != b"\xff\xd8\xff" or len(data) > MAX_FRAME_BYTES:
        _LOGGER.warning(
            "Qubo motion photo: ffmpeg failed (rc=%s, %d bytes): %s",
            proc.returncode, len(data), _redact(err.decode(errors="replace"))[-300:],
        )
        return None
    return data


def _read_and_remove(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            data = f.read()
        os.remove(path)
    except OSError:
        return None
    return data


def _cleanup(*paths: str) -> None:
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


async def _record(url: str, seconds: int, jpg: str | None, mp4: str) -> bool:
    """Record a clip (video copied as-is, audio to AAC) and optionally the first frame as JPEG."""
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-rtsp_transport", "tcp", "-i", url]
    if jpg:
        args += ["-map", "0:v:0", "-frames:v", "1", "-q:v", "4", "-update", "1", "-f", "image2", "-c:v", "mjpeg", jpg]
    args += [
        "-map", "0:v:0", "-map", "0:a:0?", "-t", str(seconds),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart", "-f", "mp4", mp4,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=seconds + GRAB_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        _LOGGER.warning("Qubo motion clip: recording did not finish in time")
        return False
    if proc.returncode != 0:
        _LOGGER.warning(
            "Qubo motion clip: ffmpeg failed (rc=%s): %s",
            proc.returncode, _redact(err.decode(errors="replace"))[-300:],
        )
        return False
    return True


class MotionCapture:
    """Listens to one camera's events and saves a frame on motion/person alerts."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.device = device
        self.uuid = device.info.uuid
        self._last_ring = 0.0
        self._last_viewer = 0.0
        self._last_grab = 0.0
        self._busy = False

    @callback
    def handle(self, data: dict[str, Any]) -> None:
        if data["device_uuid"] != self.uuid:
            return
        now = time.monotonic()
        svc, ev = data.get("service"), data.get("event_name")
        params = data.get("parameters") or {}
        if svc == "doorbell" or (svc == "call" and ev == "incomingCall"):
            self._last_ring = now  # ring photos come from Qubo itself
            return
        if svc in ("p2pStreaming", "streamControl") and not self._busy:
            self._last_viewer = now  # someone is watching in the Qubo app
            return
        if svc != "recordingControl" or ev != "stateChanged":
            return
        kind = MOTION_CAUSES.get(str(params.get("cause", "")).upper())
        if not kind or params.get("record", "start") != "start":
            return
        opts = self.entry.options
        if not opts.get(CONF_HISTORY_ENABLED, DEFAULT_HISTORY_ENABLED):
            return
        want_photo = opts.get(CONF_MOTION_SNAPSHOTS, DEFAULT_MOTION_SNAPSHOTS)
        want_video = opts.get(CONF_VIDEO_ENABLED, DEFAULT_VIDEO_ENABLED)
        if not (want_photo or want_video):
            return
        cooldown = int(opts.get(CONF_MOTION_COOLDOWN, DEFAULT_MOTION_COOLDOWN))
        if self._busy or now - self._last_grab < cooldown:
            return
        if now - self._last_ring < RING_SNAPSHOT_WINDOW or now - self._last_viewer < VIEWER_GRACE:
            return
        self._busy = True
        self._last_grab = now
        seconds = int(opts.get(CONF_VIDEO_SECONDS, DEFAULT_VIDEO_SECONDS)) if want_video else 0
        self.hass.async_create_background_task(
            self._async_capture(kind, want_photo, seconds), f"{DOMAIN} motion capture"
        )

    async def _async_capture(self, kind: str, want_photo: bool, seconds: int) -> None:
        when = dt_util.now()
        started = time.monotonic()
        photo: bytes | None = None
        tmp_dir = self.hass.config.path(DOMAIN, "tmp")
        stem = os.path.join(tmp_dir, f"{self.uuid}_{int(started * 1000)}")
        jpg, mp4 = (f"{stem}.jpg" if want_photo else None), f"{stem}.mp4"
        clip_ok = False
        try:
            url = await self.device.start_stream(quality="high")
            if url:
                if seconds:
                    await self.hass.async_add_executor_job(lambda: os.makedirs(tmp_dir, exist_ok=True))
                    clip_ok = await _record(str(url), seconds, jpg, mp4)
                    if jpg:
                        photo = await self.hass.async_add_executor_job(_read_and_remove, jpg)
                        if photo and photo[:3] != b"\xff\xd8\xff":
                            photo = None
                else:
                    photo = await _grab_frame(str(url))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qubo motion capture failed: %s", _redact(f"{type(err).__name__}: {err}"))
        finally:
            try:
                await self.device.stop_stream()
            except Exception:  # noqa: BLE001
                pass  # best effort; Qubo closes the session when the socket drops
            self._busy = False
        _LOGGER.debug("Qubo %s capture finished in %.1fs", kind, time.monotonic() - started)
        if photo:
            await async_save_to_history(self.hass, self.entry.entry_id, photo, "jpg", kind, when)
        if clip_ok:
            if await async_save_clip_to_history(self.hass, self.entry.entry_id, mp4, kind, when):
                return
        if seconds:
            await self.hass.async_add_executor_job(_cleanup, mp4, *( [jpg] if jpg else [] ))
