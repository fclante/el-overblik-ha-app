"""El-Overblik HA: read-only ElOverblik Customer API integration."""

from datetime import date
from typing import Any

import probatio as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.start import async_at_started

from .api import CustomerApi, RequestGate
from .const import CONF_METERS, CONF_TOKEN, DOMAIN, LEGACY_NAME, NAME, PLATFORMS
from .coordinator import Coordinator
from .models import ApiError, AuthenticationError, EndpointUnavailableError, timestamp

type EloverblikEntry = ConfigEntry[Coordinator]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register actions once, including while entries are unloaded."""

    async def handle(call: ServiceCall) -> dict[str, Any]:
        entry = hass.config_entries.async_get_entry(call.data["entry_id"])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
            or not hasattr(entry, "runtime_data")
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="entry_unavailable"
            )
        coordinator: Coordinator = entry.runtime_data
        if call.service == "import_history":
            try:
                start = date.fromisoformat(call.data["start"])
                end = date.fromisoformat(call.data["end"])
                return coordinator.start_history(start, end)
            except ValueError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="invalid_period"
                ) from err
        meters = call.data.get("metering_points", coordinator.meters)
        if not meters or set(meters) - set(coordinator.meters):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unknown_meter"
            )
        if call.service == "get_charges":
            return {
                "meters": {
                    meter: coordinator.states[meter].charges for meter in meters
                },
                "cost_status": "unsupported_semantics",
                "errors": {
                    meter: coordinator.states[meter].metadata_errors.get("charges")
                    for meter in meters
                },
                "last_update_success": coordinator.last_update_success,
            }
        try:
            result = await coordinator.api.dated_charges(
                meters, timestamp(call.data["start"]), timestamp(call.data["end"])
            )
        except EndpointUnavailableError as err:
            coordinator.dated_charges_available = False
            coordinator.async_update_listeners()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="dated_charges_unavailable"
            ) from err
        except AuthenticationError as err:
            entry.async_start_reauth(hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="authentication_failed"
            ) from err
        except (ApiError, ValueError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="charge_query_failed"
            ) from err
        coordinator.dated_charges_available = True
        coordinator.async_update_listeners()
        return result

    base: dict[Any, Any] = {vol.Required("entry_id"): str}
    hass.services.async_register(
        DOMAIN,
        "import_history",
        handle,
        schema=vol.Schema(
            {
                **base,
                vol.Required("start"): str,
                vol.Required("end"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_charges",
        handle,
        schema=vol.Schema(
            {
                **base,
                vol.Optional("metering_points"): [str],
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_charge_schedule",
        handle,
        schema=vol.Schema(
            {
                **base,
                vol.Optional("metering_points"): [str],
                vol.Required("start"): str,
                vol.Required("end"): str,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EloverblikEntry) -> bool:
    if entry.title == LEGACY_NAME:
        hass.config_entries.async_update_entry(entry, title=NAME)
    gate = hass.data.setdefault(f"{DOMAIN}_gate", RequestGate())
    coordinator = Coordinator(
        hass,
        entry,
        CustomerApi(async_get_clientsession(hass), entry.data[CONF_TOKEN], gate),
    )
    entry.runtime_data = coordinator
    await coordinator.load()
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))

    @callback
    def started(hass: HomeAssistant) -> None:
        entry.async_create_background_task(
            hass, coordinator.initial_update(), f"{NAME} initial update"
        )

    entry.async_on_unload(async_at_started(hass, started))
    return True


async def _reload(hass: HomeAssistant, entry: EloverblikEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EloverblikEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: EloverblikEntry, device_entry: DeviceEntry
) -> bool:
    """Require reconfiguration before removing a configured meter device."""
    return not any(
        (DOMAIN, meter) in device_entry.identifiers for meter in entry.data[CONF_METERS]
    )
