"""Config flow for Qubo Doorbell."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from qubopy import QuboAuth, QuboAuthError, QuboClient, QuboConnectionError

from .const import (
    CONF_DEVICE_ID,
    CONF_HISTORY_ENABLED,
    CONF_HISTORY_FOLDER,
    CONF_HISTORY_MAX_MB,
    CONF_MOTION_COOLDOWN,
    CONF_MOTION_SNAPSHOTS,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_MAX_MB,
    CONF_VIDEO_SECONDS,
    DEFAULT_HISTORY_ENABLED,
    DEFAULT_HISTORY_FOLDER,
    DEFAULT_HISTORY_MAX_MB,
    DEFAULT_MOTION_COOLDOWN,
    DEFAULT_MOTION_SNAPSHOTS,
    DEFAULT_VIDEO_ENABLED,
    DEFAULT_VIDEO_MAX_MB,
    DEFAULT_VIDEO_SECONDS,
    DOMAIN,
)
from .history import valid_folder

SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})


async def _validate(hass, email: str, password: str, device_id: str) -> tuple[str, list[str]]:
    session = async_get_clientsession(hass)
    auth = QuboAuth(device_id=device_id, session=session)
    tokens = await auth.login_with_email(email, password, device_attribute="Home Assistant")
    devices = await QuboClient(auth, session=session).get_all_devices()
    return tokens.user_uuid, [f"{d.info.name} ({d.info.model})" for d in devices]


class QuboDoorbellConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Qubo account email and password."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return QuboOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = uuid.uuid4().hex
            try:
                user_uuid, devices = await _validate(
                    self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD], device_id
                )
            except QuboAuthError:
                errors["base"] = "invalid_auth"
            except (QuboConnectionError, OSError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_uuid)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Qubo ({user_input[CONF_EMAIL]})",
                    data={**user_input, CONF_DEVICE_ID: device_id},
                    description_placeholders={"devices": ", ".join(devices)},
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await _validate(
                    self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD], entry.data[CONF_DEVICE_ID]
                )
            except QuboAuthError:
                errors["base"] = "invalid_auth"
            except (QuboConnectionError, OSError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )


class QuboOptionsFlow(OptionsFlow):
    """Snapshot history settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HISTORY_FOLDER] = user_input[CONF_HISTORY_FOLDER].strip()
            if not valid_folder(user_input[CONF_HISTORY_FOLDER]):
                errors[CONF_HISTORY_FOLDER] = "invalid_folder"
            else:
                return self.async_create_entry(data=user_input)
        o = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(CONF_HISTORY_ENABLED, default=o.get(CONF_HISTORY_ENABLED, DEFAULT_HISTORY_ENABLED)): bool,
                vol.Required(CONF_HISTORY_FOLDER, default=o.get(CONF_HISTORY_FOLDER, DEFAULT_HISTORY_FOLDER)): str,
                vol.Required(CONF_HISTORY_MAX_MB, default=o.get(CONF_HISTORY_MAX_MB, DEFAULT_HISTORY_MAX_MB)): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=100000)
                ),
                vol.Required(CONF_MOTION_SNAPSHOTS, default=o.get(CONF_MOTION_SNAPSHOTS, DEFAULT_MOTION_SNAPSHOTS)): bool,
                vol.Required(CONF_MOTION_COOLDOWN, default=o.get(CONF_MOTION_COOLDOWN, DEFAULT_MOTION_COOLDOWN)): vol.All(
                    vol.Coerce(int), vol.Range(min=10, max=3600)
                ),
                vol.Required(CONF_VIDEO_ENABLED, default=o.get(CONF_VIDEO_ENABLED, DEFAULT_VIDEO_ENABLED)): bool,
                vol.Required(CONF_VIDEO_SECONDS, default=o.get(CONF_VIDEO_SECONDS, DEFAULT_VIDEO_SECONDS)): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=60)
                ),
                vol.Required(CONF_VIDEO_MAX_MB, default=o.get(CONF_VIDEO_MAX_MB, DEFAULT_VIDEO_MAX_MB)): vol.All(
                    vol.Coerce(int), vol.Range(min=50, max=100000)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
