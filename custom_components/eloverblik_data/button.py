"""A refresh button uses the coordinator's throttled refresh path."""

from datetime import UTC, datetime, timedelta

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EloverblikEntry
from .const import DOMAIN
from .entity import MeterEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: EloverblikEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([RefreshButton(coordinator, coordinator.meters[0], "refresh")])


class RefreshButton(MeterEntity, ButtonEntity):
    """One button per entry, attached to its first meter."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _last_press: datetime | None = None

    async def async_press(self) -> None:
        now = datetime.now(UTC)
        if self._last_press is not None and now - self._last_press < timedelta(
            minutes=1
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="refresh_busy"
            )
        self._last_press = now
        await self.coordinator.async_request_refresh()
