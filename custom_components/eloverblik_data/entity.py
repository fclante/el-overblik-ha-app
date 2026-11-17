"""Shared stable meter identity."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import Coordinator, MeterData


class MeterEntity(CoordinatorEntity[Coordinator]):
    """Keep devices stable across physical-meter and token replacement."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Coordinator, meter: str, key: str) -> None:
        super().__init__(coordinator)
        self.meter = meter
        self._attr_unique_id = f"{meter}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, meter)},
            name=f"{NAME} {meter}",
            manufacturer="Energinet",
        )

    @property
    def meter_data(self) -> MeterData:
        return self.coordinator.states[self.meter]

    @property
    def available(self) -> bool:
        """Cached readings remain visible; freshness is exposed separately."""
        return True
