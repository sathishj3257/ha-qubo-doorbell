"""Last-event sensor: shows every real-time event a Qubo device sends."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

import os

from homeassistant.util import dt as dt_util

from .const import (
    CONF_HISTORY_ENABLED,
    CONF_HISTORY_FOLDER,
    CONF_HISTORY_MAX_MB,
    CONF_MOTION_SNAPSHOTS,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_MAX_MB,
    DEFAULT_HISTORY_ENABLED,
    DEFAULT_HISTORY_FOLDER,
    DEFAULT_HISTORY_MAX_MB,
    DEFAULT_MOTION_SNAPSHOTS,
    DEFAULT_VIDEO_ENABLED,
    DEFAULT_VIDEO_MAX_MB,
    DOMAIN,
    SIGNAL_EVENT,
    SIGNAL_HISTORY,
)
from .entity import QuboEntity, is_camera_like
from .history import media_root, scan_all, valid_folder


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    rt = hass.data[DOMAIN][entry.entry_id]
    ents: list[SensorEntity] = [QuboLastEventSensor(entry.entry_id, d) for d in rt.devices]
    cams = [d for d in rt.devices if is_camera_like(d)]
    if cams:
        ents.append(QuboHistorySensor(entry, cams[0]))
    async_add_entities(ents)


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


class QuboHistorySensor(QuboEntity, SensorEntity):
    """Number of photos kept in the snapshot history (clips, sizes and settings as attributes)."""

    _attr_name = "Snapshot history"
    _attr_icon = "mdi:image-multiple-outline"
    _attr_native_unit_of_measurement = "photos"

    def __init__(self, entry: ConfigEntry, device: Any) -> None:
        super().__init__(entry.entry_id, device)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_snapshot_history"
        self._attr_native_value = 0

    def _apply(self, photos: Any, clips: Any) -> None:
        o = self._entry.options
        folder = o.get(CONF_HISTORY_FOLDER, DEFAULT_HISTORY_FOLDER)
        newest = max((s.newest for s in (photos, clips) if s and s.newest), default=None)
        oldest = min((s.oldest for s in (photos, clips) if s and s.oldest), default=None)
        self._attr_native_value = photos.count if photos else 0
        self._attr_extra_state_attributes = {
            "enabled": o.get(CONF_HISTORY_ENABLED, DEFAULT_HISTORY_ENABLED),
            "folder": f"media/{folder}",
            "size_mb": round((photos.size_bytes if photos else 0) / 1048576, 2),
            "limit_mb": int(o.get(CONF_HISTORY_MAX_MB, DEFAULT_HISTORY_MAX_MB)),
            "motion_photos": o.get(CONF_MOTION_SNAPSHOTS, DEFAULT_MOTION_SNAPSHOTS),
            "clips": clips.count if clips else 0,
            "clips_size_mb": round((clips.size_bytes if clips else 0) / 1048576, 2),
            "clips_limit_mb": int(o.get(CONF_VIDEO_MAX_MB, DEFAULT_VIDEO_MAX_MB)),
            "video_enabled": o.get(CONF_VIDEO_ENABLED, DEFAULT_VIDEO_ENABLED),
            "oldest": dt_util.utc_from_timestamp(oldest).isoformat() if oldest else None,
            "newest": dt_util.utc_from_timestamp(newest).isoformat() if newest else None,
        }

    async def _async_refresh(self) -> None:
        folder = self._entry.options.get(CONF_HISTORY_FOLDER, DEFAULT_HISTORY_FOLDER)
        photos = clips = None
        if valid_folder(folder):
            photos, clips = await self.hass.async_add_executor_job(
                scan_all, os.path.join(media_root(self.hass), folder)
            )
        self._apply(photos, clips)

    async def async_added_to_hass(self) -> None:
        await self._async_refresh()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, f"{SIGNAL_HISTORY}_{self._entry_id}", self._handle)
        )

    @callback
    def _handle(self, *_args: Any) -> None:
        async def _update() -> None:
            await self._async_refresh()
            self.async_write_ha_state()

        self.hass.async_create_task(_update(), "qubo history refresh")
