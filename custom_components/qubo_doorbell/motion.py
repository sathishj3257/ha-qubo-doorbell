"""Motion photos.

Qubo motion/person alerts don't carry a downloadable photo (only a path on the
doorbell itself), so when one arrives this briefly opens the cloud live stream,
grabs a single frame with ffmpeg, closes the stream and saves the frame into the
snapshot history.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_HISTORY_ENABLED,
    CONF_MOTION_COOLDOWN,
    CONF_MOTION_SNAPSHOTS,
    DEFAULT_HISTORY_ENABLED,
    DEFAULT_MOTION_COOLDOWN,
    DEFAULT_MOTION_SNAPSHOTS,
    DOMAIN,
    MOTION_CAUSES,
    RING_SNAPSHOT_WINDOW,
    VIEWER_GRACE,
)
from .history import async_save_to_history

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
        if not opts.get(CONF_MOTION_SNAPSHOTS, DEFAULT_MOTION_SNAPSHOTS):
            return
        cooldown = int(opts.get(CONF_MOTION_COOLDOWN, DEFAULT_MOTION_COOLDOWN))
        if self._busy or now - self._last_grab < cooldown:
            return
        if now - self._last_ring < RING_SNAPSHOT_WINDOW or now - self._last_viewer < VIEWER_GRACE:
            return
        self._busy = True
        self._last_grab = now
        self.hass.async_create_background_task(self._async_capture(kind), f"{DOMAIN} motion photo")

    async def _async_capture(self, kind: str) -> None:
        data: bytes | None = None
        started = time.monotonic()
        try:
            url = await self.device.start_stream(quality="high")
            if url:
                data = await _grab_frame(str(url))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qubo motion photo failed: %s", _redact(f"{type(err).__name__}: {err}"))
        finally:
            try:
                await self.device.stop_stream()
            except Exception:  # noqa: BLE001
                pass  # best effort; Qubo closes the session when the socket drops
            self._busy = False
        if data:
            _LOGGER.debug("Qubo %s photo grabbed in %.1fs", kind, time.monotonic() - started)
            await async_save_to_history(self.hass, self.entry.entry_id, data, "jpg", kind)
