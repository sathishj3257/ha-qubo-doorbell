"""Last-event sensor: shows every real-time event a Qubo device sends."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_EVENT
from .entity import QuboEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    rt = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(QuboLastEventSensor(entry.entry_id, d) for d in rt.devices)


class QuboLastEventSensor(QuboEntity, SensorEntity):
    """State = '<service> / <event>' of the most recent real-time event."""

    _attr_name = "Last event"
    _attr_icon = "mdi:bell-badge-outline"

    def __init__(self, entry_id: str, device: Any) -> None:
        super().__init__(entry_id, device)
        self._attr_unique_id = f"{self._uuid}_last_event"
        self._attr_native_value = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_EVENT}_{self._entry_id}", self._handle)
        )

    @callback
    def _handle(self, data: dict[str, Any]) -> None:
        if data["device_uuid"] != self._uuid:
            return
        label = " / ".join(str(x) for x in (data.get("service"), data.get("event_name")) if x)
        self._attr_native_value = (label or "event")[:255]
        self._attr_extra_state_attributes = {
            "service": data.get("service"),
            "event_name": data.get("event_name"),
            "operation_state": data.get("operation_state"),
            "parameters": data.get("parameters"),
            "received_at": datetime.fromtimestamp(data["received"], timezone.utc).isoformat(),
        }
        self.async_write_ha_state()
