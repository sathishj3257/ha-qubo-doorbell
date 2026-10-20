"""Qubo Doorbell integration (unofficial, built on qubopy)."""
from __future__ import annotations

from collections import deque
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from qubopy import QuboAuth, QuboAuthError, QuboClient, QuboConnectionError, QuboMqttListener

from .const import CONF_DEVICE_ID, DOMAIN, EVENT_QUBO, MAX_EVENT_LOG, SIGNAL_EVENT

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.IMAGE]


class QuboRuntime:
    """Holds the live Qubo session for one config entry."""

    def __init__(self, auth: Any, client: Any, devices: list[Any]) -> None:
        self.auth = auth
        self.client = client
        self.devices = devices
        self.listener: Any = None
        self.events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENT_LOG)
        self.connected = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Log in, discover devices and start the real-time event listener."""
    session = async_get_clientsession(hass)
    auth = QuboAuth(device_id=entry.data[CONF_DEVICE_ID], session=session)
    try:
        await auth.login_with_email(
            entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], device_attribute="Home Assistant"
        )
        client = QuboClient(auth, session=session)
        devices = [
            d for d in await client.get_all_devices()
            if (d.info.model or "").lower() != "mobile" and not (d.info.name or "").startswith("MobileApp_")
        ]
    except QuboAuthError as err:
        raise ConfigEntryAuthFailed(f"Qubo login failed: {err}") from err
    except (QuboConnectionError, OSError) as err:
        raise ConfigEntryNotReady(f"Cannot reach Qubo cloud: {err}") from err

    rt = QuboRuntime(auth, client, devices)
    names = {d.info.uuid: d.info.name for d in devices}
    unit_uuids = sorted({d.info.unit_uuid for d in devices if d.info.unit_uuid})

    @callback
    def _on_event(ev: Any) -> None:
        data = {
            "device_uuid": ev.device_uuid,
            "device_name": names.get(ev.device_uuid, ev.device_uuid),
            "service": ev.service,
            "event_name": ev.event_name,
            "operation_state": ev.operation_state,
            "parameters": ev.parameters,
            "qubo_timestamp": ev.timestamp,
            "received": time.time(),
        }
        rt.events.appendleft(data)
        _LOGGER.info("Qubo event from %s: %s / %s %s", data["device_name"], ev.service, ev.event_name, ev.parameters)
        hass.bus.async_fire(EVENT_QUBO, data)
        async_dispatcher_send(hass, f"{SIGNAL_EVENT}_{entry.entry_id}", data)

    async def _on_auth_failure() -> None:
        _LOGGER.warning("Qubo session expired; re-logging in")
        try:
            await auth.login_with_email(
                entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], device_attribute="Home Assistant"
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Qubo re-login failed: %s", err)
            entry.async_start_reauth(hass)

    listener = QuboMqttListener(
        client, unit_uuids=unit_uuids or None, loop=hass.loop, on_auth_failure=_on_auth_failure
    )
    listener.add_event_listener(_on_event)
    try:
        await listener.start()
        rt.connected = True
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Qubo real-time connection failed: {err}") from err
    rt.listener = listener

    async def _keep_token_fresh(_now: Any) -> None:
        try:
            await auth.get_valid_access_token()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Qubo token refresh failed: %s", err)
            await _on_auth_failure()

    entry.async_on_unload(async_track_time_interval(hass, _keep_token_fresh, timedelta(minutes=20)))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = rt
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(
        "Qubo connected: %d device(s): %s",
        len(devices),
        ", ".join(f"{d.info.name} ({d.info.model})" for d in devices),
    )
    return True


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device: Any) -> bool:
    """Allow removing stale devices from the UI."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop the listener and unload platforms."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    rt: QuboRuntime | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if rt and rt.listener:
        try:
            await rt.listener.stop()
        except Exception:  # noqa: BLE001
            pass
    return ok
