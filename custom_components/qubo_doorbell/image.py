"""Last-visitor snapshot image.

The Qubo cloud sends a short-lived, pre-signed photo link a few seconds after
each ring. The photo is downloaded immediately and kept on disk (private,
outside /config/www), so it survives link expiry and Home Assistant restarts
and stays until the next visitor replaces it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_EVENT
from .entity import QuboEntity, is_camera_like

_LOGGER = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    rt = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(QuboSnapshotImage(hass, entry.entry_id, d) for d in rt.devices if is_camera_like(d))


def _read_file(path: str) -> tuple[bytes, float] | None:
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read(), os.path.getmtime(path)


def _sniff_image_type(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return None


def _write_file(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


class QuboSnapshotImage(QuboEntity, ImageEntity):
    """Shows the most recent visitor photo, stored locally."""

    _attr_name = "Last visitor"
    _attr_icon = "mdi:account-box-outline"
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, entry_id: str, device: Any) -> None:
        QuboEntity.__init__(self, entry_id, device)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{self._uuid}_last_visitor"
        self._path = hass.config.path(DOMAIN, f"{self._uuid}_last_visitor.jpg")
        self._image: bytes | None = None
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        stored = await self.hass.async_add_executor_job(_read_file, self._path)
        if stored:
            self._image, mtime = stored
            self._attr_content_type = _sniff_image_type(self._image) or "image/jpeg"
            self._attr_image_last_updated = datetime.fromtimestamp(mtime, timezone.utc)
            self._attr_extra_state_attributes = {"captured_at": self._attr_image_last_updated.isoformat()}
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_EVENT}_{self._entry_id}", self._handle)
        )

    async def async_image(self) -> bytes | None:
        return self._image

    @callback
    def _handle(self, data: dict[str, Any]) -> None:
        if data["device_uuid"] != self._uuid or data.get("event_name") != "snapshotAvailable":
            return
        url = (data.get("parameters") or {}).get("snapshotUrl")
        if url:
            self.hass.async_create_task(self._async_store(url), f"{DOMAIN} snapshot download")

    async def _async_store(self, url: str) -> None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=30) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Qubo snapshot download failed (HTTP %s)", resp.status)
                    return
                data = await resp.read()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qubo snapshot download error: %s", err)
            return
        if not data or len(data) > MAX_IMAGE_BYTES:
            _LOGGER.warning("Qubo snapshot has unexpected size (%s bytes)", len(data or b""))
            return
        # Qubo's storage serves photos as "binary/octet-stream", so detect the type from the bytes.
        ctype = _sniff_image_type(data)
        if ctype is None:
            _LOGGER.warning("Qubo snapshot is not a JPEG/PNG image (%d bytes)", len(data))
            return
        await self.hass.async_add_executor_job(_write_file, self._path, data)
        self._image = data
        self._attr_content_type = ctype
        self._attr_image_last_updated = dt_util.utcnow()
        self._attr_extra_state_attributes = {"captured_at": self._attr_image_last_updated.isoformat()}
        self.async_write_ha_state()
        _LOGGER.info("Stored new Qubo visitor snapshot (%d bytes)", len(data))
