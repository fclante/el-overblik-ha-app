"""Use real Core registries, panels, templates and translated dashboard configs."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components import frontend
from homeassistant.components.lovelace import LOVELACE_DATA, LovelaceData
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template

from custom_components.eloverblik_data.api import CustomerApi
from custom_components.eloverblik_data.binary_sensor import StaleSensor
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
    entry = make_entry(
        options={CONF_METER_SETTINGS: {METER: {"area": "DK2", "contract": "fixed"}}}
    )
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


@pytest.mark.parametrize(
    ("language", "overview", "empty", "charges"),
    [
        ("da", "Overblik", "Venter på historiske målinger", "ElOverblik-tariffer"),
        ("fr", "Overview", "Waiting for historical readings", "ElOverblik charges"),
    ],
)
async def test_dashboard_copy_uses_own_catalog_and_english_fallback(
    hass, language, overview, empty, charges
):
    hass.config.language = language
    hass.data[LOVELACE_DATA] = LovelaceData("storage", {}, None, {})
    entry = make_entry()
    await async_setup_dashboard(
        hass, Coordinator(hass, entry, AsyncMock(spec=CustomerApi))
    )
    dashboard = hass.data[DATA_KEY]
    next(iter(dashboard.owners.values())).states[METER].metadata_errors["charges"] = (
        20010
    )
    config = await dashboard.async_load(False)
    assert config["views"][0]["title"] == overview
    assert empty in json.dumps(config, ensure_ascii=False)
    assert charges in json.dumps(config, ensure_ascii=False)
    await entry._async_process_on_unload(hass)


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


@pytest.fixture
async def dashboard_context(hass):
    hass.data[LOVELACE_DATA] = LovelaceData("storage", {}, None, {})
    entry = make_entry()
    with patch(
        "custom_components.eloverblik_data.async_setup_entry", return_value=True
    ):
        await hass.config_entries.async_add(entry)
    coordinator = Coordinator(hass, entry, AsyncMock(spec=CustomerApi))
    await async_setup_dashboard(hass, coordinator)
    yield hass.data[DATA_KEY], coordinator
    await coordinator.entry._async_process_on_unload(hass)


@pytest.mark.parametrize(
    ("age", "old"), [(timedelta(days=1), False), (timedelta(days=4), True)]
)
async def test_consumption_freshness_is_independent_of_charges_and_production(
    hass, dashboard_context, age, old
):
    dashboard, coordinator = dashboard_context
    data = coordinator.states[METER]
    at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    end = at - age
    data.history.streams = {
        "consumption": {
            end - timedelta(hours=1): Reading(
                end - timedelta(hours=1), Decimal("1.2"), "A04"
            )
        },
        "production": {at: Reading(at, Decimal("0.3"), "A04")},
    }
    data.metadata_errors["charges"] = 20010
    content = Template(
        dashboard.reading_status(data, "consumption")["content"], hass
    ).async_render()
    assert end.astimezone(DENMARK).strftime("%d/%m/%Y %H:%M") in content
    assert ("Readings are more than three days old" in content) is old
    messages = Template(
        dashboard.source_status(coordinator, METER)[0]["content"], hass
    ).async_render()
    assert "ElOverblik charges" in messages
    assert "Access denied" in messages
    assert "ElOverblik readings request failed" not in messages
    # Existing automation semantics still include metadata errors and all streams.
    assert StaleSensor(coordinator, METER, "stale").is_on
    data.metadata_errors.clear()
    assert not StaleSensor(coordinator, METER, "stale").is_on


async def test_reading_age_threshold_updates_without_a_cloud_fetch(
    hass, dashboard_context
):
    dashboard, coordinator = dashboard_context
    end = datetime(2026, 11, 17, tzinfo=UTC)
    start = end - timedelta(hours=1)
    data = coordinator.states[METER]
    data.history.streams = {"consumption": {start: Reading(start, Decimal(1), "A04")}}
    template = Template(dashboard.reading_status(data, "consumption")["content"], hass)
    with patch("homeassistant.util.dt.now") as clock:
        clock.return_value = end + timedelta(days=3)
        assert "Readings are more than three days old" not in template.async_render()
        clock.return_value += timedelta(seconds=1)
        assert "Readings are more than three days old" in template.async_render()


async def test_waiting_import_and_simultaneous_source_failures(hass, dashboard_context):
    dashboard, coordinator = dashboard_context
    coordinator.job_status["status"] = "running"
    waiting = Template(
        dashboard.reading_status(coordinator.states[METER], "consumption")["content"],
        hass,
    ).async_render()
    assert "Waiting for historical readings" in waiting
    assert "failed" not in dashboard.source_status(coordinator, METER)[0]["content"]
    coordinator.job_status["status"] = "error"
    coordinator.last_update_success = False
    coordinator.states[METER].error = "api_20010"
    coordinator.states[METER].metadata_errors["details"] = "unrecognized_code"
    messages = dashboard.source_status(coordinator, METER)[0]["content"]
    assert "connection failed" in messages
    assert "readings: access denied" in messages
    assert "meter details" in messages
    assert "Request failed" in messages
    assert "History import has failed requests" in messages


async def test_sparse_overview_chart_follows_compact_kpis(hass, dashboard_context):
    dashboard, coordinator = dashboard_context
    data = coordinator.states[METER]
    data.history.streams = {"consumption": {}}
    registry = er.async_get(hass)
    for key in ("consumption_day", "consumption_month", "stale"):
        registry.async_get_or_create(
            "binary_sensor" if key == "stale" else "sensor",
            DOMAIN,
            f"{METER}_{key}",
            config_entry=coordinator.entry,
        )
    overview = dashboard.build()["views"][0]
    cards = overview["sections"][1]["cards"]
    kpis = next(card for card in cards if card["type"] == "grid")
    assert len(kpis["cards"]) == 2
    assert kpis["columns"] == 2
    chart = next(card for card in cards if card["type"] == "statistics-graph")
    assert cards.index(chart) > cards.index(kpis)
    assert chart["grid_options"]["columns"] == "full"
    assert not any(card["type"] in {"button", "conditional"} for card in cards)
    text = json.dumps(cards)
    assert "Select DK1/DK2" in text
    assert "Delayed or unavailable data" not in text
    assert "[Details](/el-overblik-ha/meter-" in text


async def test_configured_area_and_disabled_entities_are_not_missing_setup(
    hass, dashboard_context
):
    dashboard, coordinator = dashboard_context
    hass.config_entries.async_update_entry(
        coordinator.entry,
        options={CONF_METER_SETTINGS: {METER: {"area": "DK1"}}},
    )
    registry = er.async_get(hass)
    for key in ("market_price", "cheapest_hour", "energy_cost", "market_difference"):
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{METER}_{key}", config_entry=coordinator.entry
        )
    config = dashboard.build()
    overview = json.dumps(config["views"][0])
    assert "market_price" in overview
    assert "energy_cost" not in overview
    assert "market_difference" not in overview
    assert "Select DK1/DK2" not in overview
    assert "Optional: add your energy contract" in overview
    price_id = registry.async_get_entity_id("sensor", DOMAIN, f"{METER}_market_price")
    registry.async_update_entity(price_id, disabled_by=er.RegistryEntryDisabler.USER)
    serialized = json.dumps(dashboard.build())
    assert price_id not in serialized
    assert "Select DK1/DK2" not in serialized
    assert "entities are disabled or not yet available" in serialized


async def test_production_only_meter_and_missing_summary_entities(
    hass, dashboard_context
):
    dashboard, coordinator = dashboard_context
    at = datetime.now(UTC) - timedelta(hours=2)
    coordinator.states[METER].history.streams = {
        "production": {at: Reading(at, Decimal("0.3"), "A04")}
    }
    registry = er.async_get(hass)
    month = registry.async_get_or_create(
        "sensor", DOMAIN, f"{METER}_production_month", config_entry=coordinator.entry
    )
    hass.states.async_set(
        month.entity_id, 0.3, {"reported_hours": 1, "expected_hours": 2}
    )
    cards = dashboard.build()["views"][0]["sections"][1]["cards"]
    rendered = "\n".join(
        Template(card["content"], hass).async_render()
        for card in cards
        if card["type"] == "markdown"
    )
    assert "Production readings through" in rendered
    assert "Consumption readings through" not in rendered
    assert "1 / 2 h" in rendered
    chart = next(card for card in cards if card["type"] == "statistics-graph")
    assert chart["entities"][0]["entity"] == f"{DOMAIN}:{METER}_production"


@pytest.mark.parametrize(
    ("error", "price", "fetched", "expected"),
    [
        (None, "unknown", False, "Waiting for the first public"),
        (None, "unknown", True, "No price covers the current interval"),
        ("connection_error", "-0.2", True, "cached price is still valid"),
        ("connection_error", "unknown", True, "No price covers the current interval"),
        (None, "-0.2", True, "Public market price is available"),
    ],
)
async def test_public_price_status_is_independent_of_consumption(
    hass, dashboard_context, error, price, fetched, expected
):
    dashboard, coordinator = dashboard_context
    entity = "sensor.synthetic_price"
    hass.states.async_set(
        entity,
        price,
        {
            "market_error": error,
            "fetched_at": datetime.now(UTC).isoformat() if fetched else None,
            "tomorrow": {"complete": False, "intervals": []},
        },
    )
    content = Template(dashboard.price_status(entity)["content"], hass).async_render()
    assert expected in content
    assert ("Public market-price refresh failed" in content) is bool(error)
    assert not dashboard.source_status(coordinator, METER)
    tomorrow = Template(
        dashboard.schedule(entity, "tomorrow")["content"], hass
    ).async_render()
    assert ("Tomorrow's prices are not yet published" in tomorrow) is bool(
        fetched and not error
    )
