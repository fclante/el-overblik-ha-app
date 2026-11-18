"""Shared, synthetic API fixtures; never use customer credentials."""

from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientSession, TCPConnector, ThreadedResolver
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity_registry,
    floor_registry,
    frame,
    label_registry,
)
from homeassistant.helpers.recorder import async_initialize_recorder

from custom_components.eloverblik_data.const import (
    CONF_METERS,
    CONF_TOKEN,
    DOMAIN,
    NAME,
)

METER = "001234567890123456"
OTHER = "001234567890123457"


@pytest.fixture
async def hass(tmp_path):
    """Run the actual target Core with isolated on-disk configuration."""
    instance = HomeAssistant(str(tmp_path))
    instance.config.skip_pip = True
    await instance.config.async_set_time_zone("Europe/Copenhagen")
    loader.async_setup(instance)
    frame.async_setup(instance)
    async_initialize_recorder(instance)
    instance.config_entries = ConfigEntries(instance, {})
    await instance.config_entries.async_initialize()
    device_registry.async_setup(instance)
    for registry in (
        label_registry,
        floor_registry,
        area_registry,
        device_registry,
        entity_registry,
    ):
        await registry.async_load(instance)
    async with ClientSession(
        connector=TCPConnector(resolver=ThreadedResolver())
    ) as session:
        with (
            patch(
                "custom_components.eloverblik_data.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.eloverblik_data.config_flow.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.eloverblik_data.market.async_get_clientsession",
                return_value=session,
            ),
        ):
            yield instance
            for entry in instance.config_entries.async_entries():
                if entry.state is ConfigEntryState.LOADED:
                    await instance.config_entries.async_unload(entry.entry_id)
            await instance.async_stop(force=True)


def make_entry(meters=None, **kwargs):
    """Construct an entry using public Core APIs, not a version-mismatched harness."""
    return ConfigEntry(
        domain=DOMAIN,
        title=kwargs.get("title", NAME),
        version=1,
        minor_version=1,
        data={CONF_TOKEN: "synthetic-token", CONF_METERS: meters or [METER]},
        options=kwargs.get("options", {}),
        source="user",
        unique_id=None,
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )


@pytest.fixture
def api_mock():
    """Keep API responses synthetic while exercising HA's actual lifecycle."""
    with patch(
        "custom_components.eloverblik_data.config_flow.CustomerApi", autospec=True
    ) as factory:
        api = factory.return_value
        api.linked_meters = AsyncMock(
            return_value=[{"meteringPointId": METER, "hasRelation": True}]
        )
        api.details = AsyncMock(
            return_value=[
                {
                    "id": METER,
                    "success": True,
                    "result": {"meteringPointId": METER, "meterNumber": "synthetic"},
                }
            ]
        )
        yield api
