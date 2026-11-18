"""Synthetic, exact examples for energy-only estimates and future windows."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.eloverblik_data.models import Reading, day_bounds
from custom_components.eloverblik_data.pricing import (
    QUARTER,
    cheapest_hour,
    comparison,
    complete_day,
    current_price,
)


@pytest.mark.parametrize(
    "day,hours", [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)]
)
def test_costs_use_matched_dst_day_and_explicit_vat(day, hours):
    start, end = day_bounds(day)
    readings = {
        start + timedelta(hours=i): Reading(
            start + timedelta(hours=i), Decimal(2), "A04"
        )
        for i in range(hours)
    }
    prices = {start + i * QUARTER: Decimal("0.5") for i in range(hours * 4)}
    settings = {
        "contract": "fixed",
        "rate": "1.25",
        "vat_included": True,
        "effective": str(day),
    }
    result = comparison(readings, prices, settings, end)
    assert result["status"] == "ready"
    assert result["contract_cost"] == hours * 2
    assert result["market_cost"] == hours
    assert result["difference"] == hours
    assert result["difference_per_kwh"] == 0.5
    assert result["expected_hours"] == hours
    settings.update(contract="spot_markup", rate="-0.125")
    result = comparison(readings, prices, settings, end)
    assert result["difference"] == pytest.approx(-hours * 0.2)
    assert result["difference_per_kwh"] == pytest.approx(-0.1)
    settings["effective"] = str(day + timedelta(days=1))
    assert comparison(readings, prices, settings, end)["status"] == "outside_contract"
    settings["effective"] = str(day)
    prices.pop(start)
    assert comparison(readings, prices, settings, end)["status"] == "incomplete_prices"
    readings.pop(start)
    assert complete_day(readings, end)["complete"] is False
    assert comparison(readings, prices, settings, end)["status"] == "incomplete_energy"


def test_hourly_average_not_a_single_quarter_or_today_price():
    day = date(2026, 11, 1)
    start, end = day_bounds(day)
    readings = {
        start + timedelta(hours=i): Reading(
            start + timedelta(hours=i), Decimal(1), "A04"
        )
        for i in range(24)
    }
    prices = {start + i * QUARTER: Decimal(i % 4) for i in range(96)}
    settings = {
        "contract": "spot_markup",
        "rate": "0.1",
        "vat_included": False,
        "effective": str(day),
    }
    result = comparison(readings, prices, settings, end + timedelta(days=10))
    assert result["market_cost"] == 36
    assert result["contract_cost"] == 38.4
    assert result["difference"] == 2.4


def test_cheapest_hour_rejects_elapsed_and_gaps_and_breaks_ties_early():
    now = datetime(2026, 11, 1, 12, 1, tzinfo=UTC)
    start = now.replace(minute=0)
    prices = {start + i * QUARTER: Decimal(-1) for i in range(10)}
    result = cheapest_hour(prices, now)
    assert result["start"] == (start + QUARTER).isoformat()
    assert result["price"] == -1
    assert current_price(prices, now) == -1
    prices.pop(start + 3 * QUARTER)
    assert cheapest_hour(prices, now)["start"] == (start + 4 * QUARTER).isoformat()
    assert cheapest_hour(prices, start + timedelta(days=1))["price"] is None
    assert current_price(prices, start + timedelta(days=1)) is None
