"""Isolate failed meters and avoid assumptions about tariff arithmetic."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.eloverblik_data.api import CustomerApi
from custom_components.eloverblik_data.coordinator import Coordinator
from custom_components.eloverblik_data.sensor import ChargeSensor, StatusSensor

from .conftest import METER, OTHER, make_entry
from .test_models import document


def coordinator(hass):
    api = AsyncMock(spec=CustomerApi)
    instance = Coordinator(hass, make_entry([METER, OTHER]), api)
    for data in instance.states.values():
        data.history.merge = AsyncMock()
    return instance


async def test_partial_access_error_does_not_stop_healthy_meter(hass):
    instance = coordinator(hass)
    instance.api.timeseries.return_value = [
        {"id": METER, "success": False, "errorCode": 20010},
        {"id": OTHER, "success": True, "MyEnergyData_MarketDocument": document()},
    ]
    result = await instance.fetch_energy(
        [METER, OTHER], date(2026, 1, 1), date(2026, 1, 2)
    )
    assert result == {OTHER}
    assert instance.states[METER].error == "api_20010"
    instance.states[OTHER].history.merge.assert_awaited_once()
    assert StatusSensor(instance, METER, "status").native_value == "access_error"


async def test_malformed_document_isolated_and_no_zero_readings(hass):
    instance = coordinator(hass)
    instance.api.timeseries.return_value = [
        {
            "id": METER,
            "success": True,
            "MyEnergyData_MarketDocument": {"TimeSeries": [{"Period": None}]},
        },
        {"id": OTHER, "success": False, "errorCode": 30015},
    ]
    result = await instance.fetch_energy(
        [METER, OTHER], date(2026, 1, 1), date(2026, 1, 2)
    )
    # An unrecognized business type is explicitly unsupported, not interpreted.
    assert "unsupported_business_type" in instance.states[METER].notices
    assert result == {METER, OTHER}
    assert instance.states[OTHER].error == "no_data"
    instance.states[OTHER].history.merge.assert_awaited_once_with({})


async def test_contract_failure_isolated(hass):
    instance = coordinator(hass)
    instance.api.timeseries.return_value = [
        {
            "id": METER,
            "success": True,
            "MyEnergyData_MarketDocument": document(unit="BAD"),
        },
        {"id": OTHER, "success": True, "MyEnergyData_MarketDocument": document()},
    ]
    assert await instance.fetch_energy(
        [METER, OTHER], date(2026, 1, 1), date(2026, 1, 2)
    ) == {OTHER}
    assert instance.states[METER].error == "api_contract"
    instance.states[METER].history.merge.assert_not_awaited()


async def test_backfill_continues_other_meters_and_resumes(hass):
    instance = coordinator(hass)
    instance.fetch_energy = AsyncMock(
        side_effect=lambda meters, start, end: set(meters) - {METER}
    )
    instance.job_status = {"status": "running"}
    await instance._history_job(date(2026, 1, 1), date(2026, 2, 2), resume=True)
    assert instance.job_status["status"] == "error"
    assert instance.job_status["failed_meter_count"] == 1
    assert instance.states[METER].history.checkpoint is None
    assert instance.states[OTHER].history.checkpoint == "2026-02-02"
    calls = instance.fetch_energy.await_count
    await instance._history_job(date(2026, 1, 2), date(2026, 2, 2), resume=True)
    # An advancing rolling start must not re-download the healthy meter's history.
    assert instance.fetch_energy.await_count == calls + 1


async def test_charge_snapshots_do_not_claim_current_or_full_cost(hass):
    instance = coordinator(hass)
    state = instance.states[METER]
    state.charges = {
        "subscriptions": [
            {
                "priceId": "fixed",
                "name": "Fixed",
                "owner": "grid",
                "price": 7.5,
                "quantity": 2,
                "periodType": "DAY",
                "validFromDate": "2099-01-01",
            }
        ]
    }
    charge = ChargeSensor(
        instance, METER, "subscriptions", "subscriptions_grid_fixed_2099-01-01"
    )
    assert charge.native_value == 7.5
    assert charge.native_unit_of_measurement == "DKK"
    assert charge.extra_state_attributes["quantity"] == 2
    assert charge.extra_state_attributes["current_rate_available"] is False
    state.metadata_errors["charges"] = 20010
    assert not charge.available
    assert StatusSensor(instance, METER, "status").native_value == "access_error"


async def test_dated_charges_require_bounds(hass):
    api = CustomerApi(AsyncMock(), "synthetic-token", AsyncMock())
    api.request = AsyncMock(return_value={"results": [], "chargeInformations": []})
    at = datetime(2026, 1, 1, tzinfo=UTC)
    await api.dated_charges([METER], at, at + timedelta(days=1))
    assert api.request.await_args.args[2] == {
        "query": [
            {
                "meteringPointId": METER,
                "from": at.isoformat(),
                "to": (at + timedelta(days=1)).isoformat(),
            }
        ]
    }
    for start, end, meters in [
        (at, at + timedelta(days=32), [METER]),
        (at.replace(tzinfo=None), at, [METER]),
        (at, at + timedelta(days=1), [METER] * 11),
    ]:
        with pytest.raises(ValueError):
            await api.dated_charges(meters, start, end)
