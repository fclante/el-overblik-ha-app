"""Freshness is distinct from a successful cloud request."""

from datetime import UTC, datetime, timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import EloverblikEntry
from .entity import MeterEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: EloverblikEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        StaleSensor(entry.runtime_data, meter, "stale")
        for meter in entry.runtime_data.meters
    )


class StaleSensor(MeterEntity, BinarySensorEntity):
    """Highlight upstream data older than three days without inventing an SLA."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._tick, timedelta(hours=1))
        )

    async def _tick(self, now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        latest = self.meter_data.latest_measurement()
        return (
            not self.coordinator.last_update_success
            or self.meter_data.error is not None
            or bool(self.meter_data.metadata_errors)
            or latest is None
            or datetime.now(UTC) - latest > timedelta(days=3)
        )
