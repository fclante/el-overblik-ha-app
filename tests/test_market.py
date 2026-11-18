"""Public-source parsing, caching and failure isolation without live requests."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from aiohttp import web

from custom_components.eloverblik_data.market import MarketCoordinator, parse_prices
from custom_components.eloverblik_data.models import ContractError, day_bounds
from custom_components.eloverblik_data.pricing import QUARTER


def test_public_source_utc_conversion_negative_and_conflicting_records():
    record = {
        "TimeUTC": "2026-10-25T01:15:00",
        "PriceArea": "DK2",
        "DayAheadPriceDKK": -250,
    }
    prices = parse_prices([record, record])
    assert prices["DK2"] == {
        datetime(2026, 10, 25, 1, 15, tzinfo=UTC): Decimal("-0.25")
    }
    for changed in (
        {"DayAheadPriceDKK": "NaN"},
        {"PriceArea": "DE"},
        {"TimeUTC": "2026-10-25T01:16:00"},
    ):
        with pytest.raises(ContractError):
            parse_prices([{**record, **changed}])
    with pytest.raises(ContractError):
        parse_prices([record, {**record, "DayAheadPriceDKK": 123}])


async def test_shared_daily_requests_persist_and_rate_limits_remain_explicit(
    hass, aiohttp_server
):
    calls = []
    limited = False

    async def prices(request):
        calls.append(request.query["start"])
        if limited:
            return web.Response(status=429, headers={"Retry-After": "7200"})
        day = date.fromisoformat(request.query["start"])
        start, end = day_bounds(day)
        return web.json_response(
            {
                "records": [
                    {
                        "TimeUTC": (start + i * QUARTER)
                        .replace(tzinfo=None)
                        .isoformat(),
                        "PriceArea": area,
                        "DayAheadPriceDKK": 500,
                    }
                    for area in ("DK1", "DK2")
                    for i in range(int((end - start) / QUARTER))
                ]
            }
        )

    app = web.Application()
    app.router.add_get("/prices", prices)
    server = await aiohttp_server(app)
    coordinator = MarketCoordinator(hass)
    now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    with (
        patch(
            "custom_components.eloverblik_data.market.URL",
            str(server.make_url("/prices")),
        ),
        patch(
            "custom_components.eloverblik_data.market.datetime", wraps=datetime
        ) as clock,
    ):
        clock.now.return_value = now
        coordinator.owners = {
            "one": lambda: {date(2026, 11, 17)},
            "two": lambda: {date(2026, 11, 17)},
        }
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert calls == ["2026-11-17", "2026-11-18", "2026-11-19"]
        await coordinator.async_refresh()
        assert len(calls) == 3
        restored = MarketCoordinator(hass)
        await restored.load()
        assert restored.data == coordinator.data
        limited = True
        clock.now.return_value = now + timedelta(hours=7)
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        assert coordinator.error == "rate_limited"
        count = len(calls)
        await coordinator.async_refresh()
        assert len(calls) == count
        assert coordinator.error is not None
