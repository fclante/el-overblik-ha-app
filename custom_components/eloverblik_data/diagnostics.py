"""Export an allowlist, not a redacted raw customer response."""

from typing import Any

from homeassistant.core import HomeAssistant

from . import EloverblikEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EloverblikEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "meter_count": len(coordinator.meters),
        "last_update_success": coordinator.last_update_success,
        "job_status": coordinator.job_status.get("status"),
        "meters": [
            {
                "error": state.error,
                "metadata_errors": state.metadata_errors,
                "notices": sorted(state.notices),
                "has_metadata": bool(state.details),
                "has_charges": bool(state.charges),
                "directions": {
                    direction: len(values)
                    for direction, values in state.history.streams.items()
                },
            }
            for state in coordinator.states.values()
        ],
    }
