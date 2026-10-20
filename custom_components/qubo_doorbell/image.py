"""Last-visitor snapshot image (from the Qubo cloud event)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_EVENT
from .entity import QuboEntity, is_camera_like


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    rt = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(QuboSnapshotImage(hass, entry.entry_id, d) for d in rt.devices if is_camera_like(d))


class QuboSnapshotImage(QuboEntity, ImageEntity):
    """Shows the most recent snapshot the doorbell uploaded."""

    _attr_name = "Last visitor"
    _attr_icon = "mdi:account-box-outline"

    def __init__(self, hass: HomeAssistant, entry_id: str, device: Any) -> None:
        QuboEntity.__init__(self, entry_id, device)
        ImageEntity.__init__(self, hass, verify_ssl=True)
        self._attr_unique_id = f"{self._uuid}_last_visitor"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_EVENT}_{self._entry_id}", self._handle)
        )

    @callback
    def _handle(self, data: dict[str, Any]) -> None:
        if data["device_uuid"] != self._uuid or data.get("event_name") != "snapshotAvailable":
            return
        url = (data.get("parameters") or {}).get("snapshotUrl")
        if not url:
            return
        self._attr_image_url = url
        self._cached_image = None
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()
