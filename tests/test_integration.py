"""Exercise real Core entities, recorder, storage, actions and translations."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder import statistics as recorder_statistics
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component

from custom_components.eloverblik_data.const import CONF_HISTORY, DOMAIN
from custom_components.eloverblik_data.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.eloverblik_data.models import (
    ApiError,
    EndpointUnavailableError,
    Reading,
)
from custom_components.eloverblik_data.statistics import MeterHistory

from .conftest import METER, OTHER, make_entry
from .test_models import document


async def records(hass, statistic_id):
    recorder = get_instance(hass)
    await recorder.async_block_till_done()
    return await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 1, tzinfo=UTC),
        {statistic_id},
        "hour",
        None,
        {"sum", "state", "change"},
    )


async def test_recorder_corrections_restart_and_missing(hass):
    assert await async_setup_component(hass, "recorder", {})
    await hass.async_start()
    history = MeterHistory(hass, METER)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    values = {
        at + timedelta(hours=i): Reading(at + timedelta(hours=i), Decimal(i + 1), "A04")
        for i in range(3)
    }
    await history.merge({"consumption": values})
    statistic_id = f"{DOMAIN}:{METER}_consumption"
    result = await records(hass, statistic_id)
    assert [r["sum"] for r in result[statistic_id]] == [1, 3, 6]
    assert [r["change"] for r in result[statistic_id]] == [1, 2, 3]
    restored = MeterHistory(hass, METER)
    await restored.load()
    assert restored.streams == history.streams
    await restored.merge({"consumption": {at: Reading(at, Decimal("0.5"), "A03")}})
    await restored.merge({"consumption": {at: Reading(at, Decimal("0.5"), "A03")}})
    result = await records(hass, statistic_id)
    assert [r["sum"] for r in result[statistic_id]] == [0.5, 2.5, 5.5]
    assert [r["change"] for r in result[statistic_id]] == [0.5, 2, 3]
    before = at - timedelta(hours=1)
    await restored.merge(
        {"consumption": {before: Reading(before, Decimal("0.25"), "A04")}}
    )
    result = await records(hass, statistic_id)
    assert [r["sum"] for r in result[statistic_id]] == [0.75, 2.75, 5.75]
    assert [r["change"] for r in result[statistic_id]] == [0.5, 2, 3]
    await restored.merge(
        {
            "consumption": {
                at + timedelta(hours=1): Reading(at + timedelta(hours=1), None, "A02")
            }
        }
    )
    result = await records(hass, statistic_id)
    assert [r["sum"] for r in result[statistic_id]] == [0.75, 3.75]


async def test_import_waits_for_inflight_recorder_task_before_marking_clean(hass):
    assert await async_setup_component(hass, "recorder", {})
    await hass.async_start()
    history = MeterHistory(hass, METER)
    entered = asyncio.Event()
    release = Event()
    import_statistics = recorder_statistics.import_statistics

    def delayed_import(*args):
        hass.loop.call_soon_threadsafe(entered.set)
        if not release.wait(timeout=10):
            raise RuntimeError("Test did not release the recorder import")
        return import_statistics(*args)

    recorder = get_instance(hass)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    with (
        patch.object(history, "save", new=AsyncMock()),
        patch.object(recorder, "async_get_commit_future", return_value=None),
        patch.object(
            recorder_statistics, "import_statistics", side_effect=delayed_import
        ),
    ):
        task = hass.async_create_task(
            history.merge({"consumption": {at: Reading(at, Decimal("0.5"), "A03")}})
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            assert not task.done()
            assert history.dirty
        finally:
            release.set()
            await task
    result = await records(hass, f"{DOMAIN}:{METER}_consumption")
    assert result[f"{DOMAIN}:{METER}_consumption"][0]["sum"] == 0.5
    assert not history.dirty


async def test_full_entry_entities_actions_and_redacted_diagnostics(hass):
    today = datetime.now().date()
    entry = make_entry(
        [METER, OTHER], options={CONF_HISTORY: (today - timedelta(days=1)).isoformat()}
    )

    async def energy(meters, start, end):
        return [
            {
                "id": meter,
                "success": True,
                "MyEnergyData_MarketDocument": document(start=f"{start}T00:00:00Z"),
            }
            for meter in meters
        ]

    with patch(
        "custom_components.eloverblik_data.CustomerApi", autospec=True
    ) as factory:
        api = factory.return_value
        api.timeseries = AsyncMock(side_effect=energy)
        api.details = AsyncMock(
            return_value=[
                {
                    "id": meter,
                    "success": True,
                    "result": {
                        "meterNumber": "synthetic-number",
                        "gridOperatorName": "Synthetic grid",
                        "firstConsumerPartyName": "MUST-NOT-EXPOSE",
                        "estimatedAnnualVolume": 1234,
                    },
                }
                for meter in (METER, OTHER)
            ]
        )
        api.charges = AsyncMock(
            return_value=[
                {
                    "id": meter,
                    "success": True,
                    "result": {
                        "tariffs": [
                            {
                                "priceId": "tariff",
                                "owner": "grid",
                                "name": "Synthetic tariff",
                                "prices": [{"position": "1", "price": 0.2}],
                            }
                        ],
                        "subscriptions": [],
                        "fees": [],
                    },
                }
                for meter in (METER, OTHER)
            ]
        )
        await hass.config_entries.async_add(entry)
        await hass.async_start()
        await hass.async_block_till_done(wait_background_tasks=True)
        coordinator = entry.runtime_data
        if coordinator._job:
            await coordinator._job
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert (
            len([e for e in entities if e.unique_id.endswith("consumption_latest")])
            == 2
        )
        latest = next(
            e for e in entities if e.unique_id == f"{METER}_consumption_latest"
        )
        state = hass.states.get(latest.entity_id)
        assert float(state.state) == 2.5
        assert "state_class" not in state.attributes
        diagnostics = json.dumps(await async_get_config_entry_diagnostics(hass, entry))
        assert METER not in diagnostics and OTHER not in diagnostics
        assert (
            "synthetic-token" not in diagnostics
            and "MUST-NOT-EXPOSE" not in diagnostics
        )
        response = await hass.services.async_call(
            DOMAIN,
            "get_charges",
            {"entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )
        assert response["cost_status"] == "unsupported_semantics"
        assert len(response["meters"]) == 2
        api.dated_charges.side_effect = EndpointUnavailableError(
            "The live API does not expose this endpoint"
        )
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN,
                "get_charge_schedule",
                {
                    "entry_id": entry.entry_id,
                    "start": "2026-11-01T00:00:00+01:00",
                    "end": "2026-11-02T00:00:00+01:00",
                },
                blocking=True,
                return_response=True,
            )
        assert error.value.translation_key == "dated_charges_unavailable"
        assert coordinator.dated_charges_available is False
        api.timeseries.side_effect = ApiError("Unable to reach ElOverblik")
        await coordinator.async_refresh()
        assert hass.states.get(latest.entity_id).state == state.state
        assert not coordinator.last_update_success
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert (Path(hass.config.path(".storage")) / f"{DOMAIN}.{METER}").exists()


async def test_danish_english_and_fallback(hass):
    english = await async_get_translations(hass, "en", "config", {DOMAIN})
    danish = await async_get_translations(hass, "da", "config", {DOMAIN})
    fallback = await async_get_translations(hass, "zz", "config", {DOMAIN})
    key = f"component.{DOMAIN}.config.step.user.title"
    assert english[key] == "Connect ElOverblik"
    assert danish[key] == "Forbind ElOverblik"
    assert fallback[key] == english[key]


@pytest.mark.parametrize(
    "category", ["options", "entity", "services", "issues", "exceptions"]
)
async def test_all_user_facing_categories_translated(hass, category):
    english = await async_get_translations(hass, "en", category, {DOMAIN})
    danish = await async_get_translations(hass, "da", category, {DOMAIN})
    assert english
    assert english.keys() == danish.keys()
    assert english != danish
