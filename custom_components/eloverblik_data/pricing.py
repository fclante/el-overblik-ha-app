"""Explicit, energy-only comparisons against Danish wholesale prices."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from .const import DENMARK
from .models import Reading, day_bounds, summary

QUARTER = timedelta(minutes=15)
FIRST_PRICE_DAY = date(2025, 10, 1)
VAT = Decimal("1.25")
type Prices = dict[datetime, Decimal]


def complete_day(readings: dict[datetime, Reading], now: datetime) -> dict[str, Any]:
    """Find the most recent complete Danish calendar day."""
    counts: dict[date, int] = {}
    for at, reading in readings.items():
        if reading.kwh is not None:
            day = at.astimezone(DENMARK).date()
            counts[day] = counts.get(day, 0) + 1
    for day in sorted(counts, reverse=True):
        start, end = day_bounds(day)
        if end <= now and counts[day] == int((end - start).total_seconds() // 3600):
            result = summary(readings, start, end)
            if result["complete"]:
                return result
    return {"energy": None, "complete": False}


def day_prices(prices: Prices, day: date) -> list[tuple[datetime, Decimal]]:
    start, end = day_bounds(day)
    return sorted((at, price) for at, price in prices.items() if start <= at < end)


def prices_complete(prices: Prices, day: date) -> bool:
    start, end = day_bounds(day)
    return all(
        start + index * QUARTER in prices
        for index in range(int((end - start) / QUARTER))
    )


def cheapest_hour(prices: Prices, now: datetime) -> dict[str, Any]:
    """Only contiguous, entirely future four-quarter windows qualify."""
    windows = [
        (sum((prices[at + i * QUARTER] for i in range(4)), Decimal(0)) / 4, at)
        for at in prices
        if at >= now and all(at + i * QUARTER in prices for i in range(4))
    ]
    if not windows:
        return {"price": None, "reason": "not_published"}
    price, start = min(windows)
    return {
        "price": float(price),
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
    }


def comparison(
    readings: dict[datetime, Reading],
    prices: Prices,
    settings: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Never price partial days or silently backdate a contract."""
    result: dict[str, Any] = {
        "status": "configure_contract",
        "scope": "energy_only",
        "vat_basis": "excluding_vat",
        "approximation": "hourly_average_uniform_consumption",
        "effective": settings.get("effective"),
        "contract": settings.get("contract", "benchmark"),
    }
    if settings.get("contract", "benchmark") == "benchmark":
        return result
    day = complete_day(readings, now)
    if not day["complete"]:
        return {**result, "status": "incomplete_energy"}
    start = datetime.fromisoformat(day["period_start"])
    end = datetime.fromisoformat(day["period_end"])
    local_day = start.astimezone(DENMARK).date()
    result.update(day)
    if local_day < date.fromisoformat(settings["effective"]):
        return {**result, "status": "outside_contract"}
    if local_day < FIRST_PRICE_DAY:
        return {**result, "status": "unsupported_period"}
    if not prices_complete(prices, local_day):
        return {**result, "status": "incomplete_prices"}
    benchmark = Decimal(0)
    energy = Decimal(0)
    for at, reading in readings.items():
        if start <= at < end and reading.kwh is not None:
            hourly_price = (
                sum((prices[at + i * QUARTER] for i in range(4)), Decimal(0)) / 4
            )
            benchmark += reading.kwh * hourly_price
            energy += reading.kwh
    rate = Decimal(str(settings["rate"]))
    if settings["vat_included"]:
        rate /= VAT
    cost = (
        energy * rate if settings["contract"] == "fixed" else benchmark + energy * rate
    )
    return {
        **result,
        "status": "ready",
        "market_cost": float(benchmark),
        "contract_cost": float(cost),
        "difference": float(cost - benchmark),
        "difference_per_kwh": float((cost - benchmark) / energy) if energy else None,
        "effective": settings["effective"],
        "contract": settings["contract"],
    }


def current_price(prices: Prices, now: datetime) -> Decimal | None:
    at = now.astimezone(UTC)
    at = at.replace(minute=at.minute // 15 * 15, second=0, microsecond=0)
    return prices.get(at)
