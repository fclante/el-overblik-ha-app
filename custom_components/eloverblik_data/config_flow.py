"""UI configuration, using Home Assistant's native language preferences."""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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
    CONF_DASHBOARD,
    CONF_HISTORY,
    CONF_METER_SETTINGS,
    CONF_METERS,
    CONF_POLL,
    CONF_TOKEN,
    DENMARK,
    DOMAIN,
    NAME,
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
                return self.async_create_entry(title=NAME, data=data)
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
                self._options = {**self.config_entry.options, **user_input}
                configure = self._options.pop("configure_prices", False)
                if configure:
                    self._meters = list(self.config_entry.data[CONF_METERS])
                    self._index = 0
                    self._settings = dict(
                        self.config_entry.options.get(CONF_METER_SETTINGS, {})
                    )
                    return await self.async_step_meter()
                return self.async_create_entry(title="", data=self._options)
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
                    vol.Optional(
                        CONF_DASHBOARD, default=options.get(CONF_DASHBOARD, True)
                    ): bool,
                    vol.Optional("configure_prices", default=False): bool,
                }
            ),
        )

    async def async_step_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure one meter at a time; no region or contract is inferred."""
        meter = self._meters[self._index]
        previous = self._settings.get(meter, {})
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = {
                **user_input,
                "area": user_input["area"].upper()
                if user_input["area"] != "none"
                else "none",
            }
            if user_input["contract"] != "benchmark":
                try:
                    rate = Decimal(user_input["rate"])
                    if not rate.is_finite():
                        raise ValueError
                except InvalidOperation, ValueError:
                    errors["rate"] = "invalid_rate"
                try:
                    date.fromisoformat(user_input["effective"])
                except TypeError, ValueError:
                    errors["effective"] = "invalid_date"
                if user_input["area"] == "none":
                    errors["area"] = "choose_area"
                changed = any(
                    user_input[key] != previous.get(key)
                    for key in ("contract", "rate", "vat_included")
                )
                if (
                    previous.get("contract", "benchmark") != "benchmark"
                    and changed
                    and user_input["effective"] == previous.get("effective")
                    and user_input["effective"]
                    < datetime.now(DENMARK).date().isoformat()
                ):
                    errors["effective"] = "new_effective_date"
            if not errors:
                self._settings[meter] = user_input
                self._index += 1
                if self._index < len(self._meters):
                    return await self.async_step_meter()
                self._options[CONF_METER_SETTINGS] = {
                    key: value
                    for key, value in self._settings.items()
                    if key in self._meters
                }
                return self.async_create_entry(title="", data=self._options)
        values = {**previous, **(user_input or {})}
        return self.async_show_form(
            step_id="meter",
            description_placeholders={"meter": meter[-4:]},
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "area", default=values.get("area", "none").lower()
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["none", "dk1", "dk2"], translation_key="price_area"
                        )
                    ),
                    vol.Required(
                        "contract", default=values.get("contract", "benchmark")
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["benchmark", "fixed", "spot_markup"],
                            translation_key="contract",
                        )
                    ),
                    vol.Required("rate", default=values.get("rate", "0")): str,
                    vol.Required(
                        "vat_included", default=values.get("vat_included", True)
                    ): bool,
                    vol.Required(
                        "effective",
                        default=values.get(
                            "effective", datetime.now(DENMARK).date().isoformat()
                        ),
                    ): selector.DateSelector(),
                }
            ),
        )
