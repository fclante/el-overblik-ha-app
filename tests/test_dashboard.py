"""Use real Core registries, panels, templates and translated dashboard configs."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from homeassistant.components import frontend
from homeassistant.components.lovelace import LOVELACE_DATA, LovelaceData
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template

from custom_components.eloverblik_data.api import CustomerApi
from custom_components.eloverblik_data.const import (
    CONF_DASHBOARD,
    CONF_METER_SETTINGS,
    DENMARK,
    DOMAIN,
)
from custom_components.eloverblik_data.coordinator import Coordinator
from custom_components.eloverblik_data.dashboard import (
    DATA_KEY,
    URL_PATH,
    async_setup_dashboard,
)
from custom_components.eloverblik_data.market import MarketCoordinator
from custom_components.eloverblik_data.models import Reading, day_bounds
from custom_components.eloverblik_data.pricing import QUARTER

from .conftest import METER, OTHER, make_entry


async def test_managed_dashboard_uses_real_ids_and_preserves_user_dashboards(hass):
    entry = make_entry()
    other = make_entry([OTHER])
    with patch(
        "custom_components.eloverblik_data.async_setup_entry", return_value=True
    ):
        await hass.config_entries.async_add(entry)
        await hass.config_entries.async_add(other)
    # Config entries need not contact either upstream service to render a dashboard.
    coordinator = Coordinator(hass, entry, AsyncMock(spec=CustomerApi))
    second = Coordinator(hass, other, AsyncMock(spec=CustomerApi))
    lovelace = LovelaceData("storage", {}, None, {})
    hass.data[LOVELACE_DATA] = lovelace
    user_dashboard = object()
    lovelace.dashboards["user-owned"] = user_dashboard
    registry = er.async_get(hass)
    for key in ("market_price", "cheapest_hour", "energy_cost", "import_status"):
        registered = registry.async_get_or_create(
            "sensor", DOMAIN, f"{METER}_{key}", config_entry=entry
        )
        registry.async_update_entity(
            registered.entity_id, new_entity_id=f"sensor.custom_{key}"
        )
    await asyncio.gather(
        async_setup_dashboard(hass, coordinator), async_setup_dashboard(hass, second)
    )
    assert frontend.async_panel_exists(hass, URL_PATH)
    dashboard = hass.data[DATA_KEY]
    config = await dashboard.async_load(False)
    assert len(config["views"]) == 3
    serialized = json.dumps(config)
    assert "sensor.custom_market_price" in serialized
    assert "Waiting for historical readings" in serialized
    assert "sensor.el_overblik_ha" not in serialized
    for view in config["views"]:
        for section in view["sections"]:
            for card in section["cards"]:
                if card["type"] == "markdown":
                    Template(card["content"], hass).async_render()
    registry.async_update_entity(
        "sensor.custom_market_price", disabled_by=er.RegistryEntryDisabler.USER
    )
    assert "sensor.custom_market_price" not in json.dumps(dashboard.build())
    await entry._async_process_on_unload(hass)
    assert frontend.async_panel_exists(hass, URL_PATH)
    await other._async_process_on_unload(hass)
    assert not frontend.async_panel_exists(hass, URL_PATH)
    assert lovelace.dashboards == {"user-owned": user_dashboard}


async def test_dashboard_optout_and_url_collision(hass, caplog):
    hass.data[LOVELACE_DATA] = LovelaceData("storage", {}, None, {})
    entry = make_entry(options={CONF_DASHBOARD: False})
    await async_setup_dashboard(
        hass, Coordinator(hass, entry, AsyncMock(spec=CustomerApi))
    )
    assert DATA_KEY not in hass.data
    hass.data[LOVELACE_DATA].dashboards[URL_PATH] = object()
    await async_setup_dashboard(
        hass, Coordinator(hass, make_entry(), AsyncMock(spec=CustomerApi))
    )
    assert DATA_KEY not in hass.data
    assert "already in use" in caplog.text


async def test_real_price_entities_roll_over_and_unload_without_market_dependency(hass):
    now = datetime.now(UTC)
    day = now.astimezone(DENMARK).date() - timedelta(days=1)
    start, end = day_bounds(day)
    settings = {
        "area": "DK2",
        "contract": "fixed",
        "rate": "1.25",
        "vat_included": True,
        "effective": str(day),
    }
    entry = make_entry(options={CONF_METER_SETTINGS: {METER: settings}})
    with (
        patch(
            "custom_components.eloverblik_data.CustomerApi", autospec=True
        ) as factory,
        patch.object(Coordinator, "initial_update", new=AsyncMock()),
        patch.object(MarketCoordinator, "async_request_refresh", new=AsyncMock()),
    ):
        factory.return_value.details = AsyncMock(return_value=[])
        factory.return_value.charges = AsyncMock(return_value=[])
        await hass.config_entries.async_add(entry)
        coordinator = entry.runtime_data
        market = coordinator.market
        assert market is not None
        hours = int((end - start).total_seconds() // 3600)
        coordinator.states[METER].history.streams["consumption"] = {
            start + timedelta(hours=i): Reading(
                start + timedelta(hours=i), Decimal(1), "A04"
            )
            for i in range(hours)
        }
        market.data["DK2"] = {
            start + i * QUARTER: Decimal("0.5") for i in range(hours * 4)
        }
        coordinator.async_update_listeners()
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        cost_id = registry.async_get_entity_id("sensor", DOMAIN, f"{METER}_energy_cost")
        price_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{METER}_market_price"
        )
        assert hass.states.get(cost_id).state == str(float(hours))
        assert hass.states.get(price_id).state == "unknown"
        # A published price is used only during its own quarter, even from cache.
        at = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
        market.data["DK2"][at] = Decimal("-0.2")
        market.async_update_listeners()
        assert hass.states.get(price_id).state == "-0.2"
        with patch(
            "custom_components.eloverblik_data.sensor.datetime", wraps=datetime
        ) as clock:
            clock.now.return_value = at + QUARTER
            market.error = "connection_error"
            market.async_update_listeners()
            assert hass.states.get(price_id).state == "unknown"
            assert (
                hass.states.get(price_id).attributes["market_error"]
                == "connection_error"
            )
            assert hass.states.get(cost_id).state == str(float(hours))
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not market.owners
        assert not market._listeners
