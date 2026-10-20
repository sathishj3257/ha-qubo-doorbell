"""Shared entity base for Qubo devices."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class QuboEntity(Entity):
    """Base entity bound to one Qubo device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry_id: str, device: Any) -> None:
        self._entry_id = entry_id
        self._device = device
        self._uuid = device.info.uuid
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uuid)},
            name=device.info.name,
            manufacturer="Qubo",
            model=device.info.model or device.info.device_type,
        )


def is_camera_like(device: Any) -> bool:
    model = (device.info.model or "").upper()
    dtype = (device.info.device_type or "").upper()
    return model.startswith(("HCD", "HCP", "HCO")) or "CAM" in dtype or "DOORBELL" in dtype or "VDB" in dtype
