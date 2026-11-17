"""UI configuration, using Home Assistant's native language preferences."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import probatio as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CustomerApi, RequestGate
from .const import (
    CONF_ALL_HISTORY,
    CONF_HISTORY,
    CONF_METERS,
    CONF_POLL,
    CONF_TOKEN,
    DENMARK,
    DOMAIN,
)
from .models import (
    ApiError,
    AuthenticationError,
    default_start,
    earliest_start,
    parse_meters,
)


def credentials(data: Mapping[str, Any] | None = None) -> vol.Schema:
    """Do not populate the refresh token into an editable form."""
    data = data or {}
    meter_input = data.get(CONF_METERS, [])
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_METERS,
                default=meter_input
                if isinstance(meter_input, str)
                else ", ".join(meter_input),
            ): str,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure explicitly selected, already linked meters."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlow:
        return OptionsFlow()

    async def _validate(
        self, user_input: dict[str, Any], exclude: str | None = None
    ) -> dict[str, Any]:
        meters = parse_meters(user_input[CONF_METERS])
        for entry in self._async_current_entries():
            if entry.entry_id != exclude and set(meters) & set(entry.data[CONF_METERS]):
                raise ValueError("overlapping_meters")
        gate = self.hass.data.setdefault(f"{DOMAIN}_gate", RequestGate())
        api = CustomerApi(
            async_get_clientsession(self.hass), user_input[CONF_TOKEN].strip(), gate
        )
        linked = await api.linked_meters()
        available = {
            item["meteringPointId"] for item in linked if item.get("hasRelation")
        }
        if set(meters) - available:
            raise ValueError("missing_relation")
        details = await api.details(meters)
        accessible = {item.get("id") for item in details if item.get("success")}
        if set(meters) - accessible:
            raise ValueError("missing_relation")
        return {CONF_TOKEN: user_input[CONF_TOKEN].strip(), CONF_METERS: meters}

    async def _form(
        self,
        step: str,
        user_input: dict[str, Any] | None,
        entry: config_entries.ConfigEntry | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = await self._validate(
                    user_input, entry.entry_id if entry else None
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            except ValueError as err:
                errors["base"] = (
                    str(err)
                    if str(err) in {"overlapping_meters", "missing_relation"}
                    else "invalid_meters"
                )
            else:
                if entry:
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                return self.async_create_entry(title="ElOverblik Data", data=data)
        return self.async_show_form(
            step_id=step,
            data_schema=credentials(entry.data if entry else user_input),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._form("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._form(
            "reconfigure", user_input, self._get_reconfigure_entry()
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._form("reauth_confirm", user_input, self._get_reauth_entry())


class OptionsFlow(config_entries.OptionsFlow):
    """History and polling options; language remains native HA configuration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        today = datetime.now(DENMARK).date()
        errors: dict[str, str] = {}
        if user_input is not None:
            start = user_input[CONF_HISTORY]
            try:
                parsed = date.fromisoformat(start)
                if (
                    not user_input[CONF_ALL_HISTORY]
                    and not earliest_start(today) <= parsed <= today
                ):
                    raise ValueError
            except TypeError, ValueError:
                errors[CONF_HISTORY] = "invalid_date"
            else:
                return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ALL_HISTORY, default=options.get(CONF_ALL_HISTORY, False)
                    ): bool,
                    vol.Required(
                        CONF_HISTORY,
                        default=options.get(
                            CONF_HISTORY, default_start(today).isoformat()
                        ),
                    ): selector.DateSelector(),
                    vol.Required(CONF_POLL, default=options.get(CONF_POLL, 6)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=24)
                    ),
                }
            ),
        )
