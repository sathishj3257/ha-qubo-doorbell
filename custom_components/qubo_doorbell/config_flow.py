"""Config flow for Qubo Doorbell."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from qubopy import QuboAuth, QuboAuthError, QuboClient, QuboConnectionError

from .const import CONF_DEVICE_ID, DOMAIN

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
