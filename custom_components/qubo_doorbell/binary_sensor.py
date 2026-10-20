"""Doorbell ring sensor (turns on briefly when the bell is pressed)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, RING_KEYWORDS, RING_ON_SECONDS, SIGNAL_EVENT
from .entity import QuboEntity, is_camera_like


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    rt = hass.data[DOMAIN][entry.entry_id]
    ents: list[BinarySensorEntity] = []
    for d in rt.devices:
        if (d.info.model or "").upper().startswith("HCD"):
            ents.append(QuboRingSensor(entry.entry_id, d))
        if is_camera_like(d):
            ents.append(QuboMotionSensor(entry.entry_id, d))
    async_add_entities(ents)


def _text(data: dict[str, Any]) -> str:
    return " ".join(str(data.get(k) or "") for k in ("service", "event_name", "parameters")).lower()


class _PulseSensor(QuboEntity, BinarySensorEntity):
    _match: tuple[str, ...] = ()

    def __init__(self, entry_id: str, device: Any) -> None:
        super().__init__(entry_id, device)
        self._attr_is_on = False
        self._cancel = None
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_EVENT}_{self._entry_id}", self._handle)
        )

    def _matches(self, data: dict[str, Any]) -> bool:
        return any(k in _text(data) for k in self._match)

    @callback
    def _handle(self, data: dict[str, Any]) -> None:
        if data["device_uuid"] != self._uuid or not self._matches(data):
            return
        self._attr_is_on = True
        self._attr_extra_state_attributes = {"service": data.get("service"), "event_name": data.get("event_name")}
        self.async_write_ha_state()
        if self._cancel:
            self._cancel()
        self._cancel = async_call_later(self.hass, RING_ON_SECONDS, self._off)

    @callback
    def _off(self, _now: Any) -> None:
        self._cancel = None
        self._attr_is_on = False
        self.async_write_ha_state()


class QuboRingSensor(_PulseSensor):
    _attr_name = "Ring"
    _attr_icon = "mdi:doorbell"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _match = RING_KEYWORDS

    def __init__(self, entry_id: str, device: Any) -> None:
        super().__init__(entry_id, device)
        self._attr_unique_id = f"{self._uuid}_ring"

    def _matches(self, data: dict[str, Any]) -> bool:
        # Verified on HCD04C: a button press sends service=doorbell, event=doorbellPressed
        return data.get("service") == "doorbell" and data.get("event_name") == "doorbellPressed"


class QuboMotionSensor(_PulseSensor):
    _attr_name = "Motion"
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _match = ("motion", "person", "ooi")

    def __init__(self, entry_id: str, device: Any) -> None:
        super().__init__(entry_id, device)
        self._attr_unique_id = f"{self._uuid}_motion"
