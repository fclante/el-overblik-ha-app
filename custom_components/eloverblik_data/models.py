"""Normalize API time series without inventing measurements."""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .const import DENMARK


class ApiError(Exception):
    """A sanitized upstream failure."""


class AuthenticationError(ApiError):
    """The refresh token must be replaced."""


class EndpointUnavailableError(ApiError):
    """The live API does not expose a documented endpoint."""


class ContractError(ApiError):
    """The response cannot safely be interpreted."""


def parse_meters(value: str | list[str]) -> list[str]:
    """Keep identifiers as strings, including leading zeroes."""
    items = value.split(",") if isinstance(value, str) else value
    result = list(dict.fromkeys(item.strip() for item in items if item.strip()))
    if not result or any(re.fullmatch(r"[0-9]{18}", item) is None for item in result):
        raise ValueError("Metering points must be 18 ASCII digits")
    return result


def timestamp(value: str) -> datetime:
    """Require a timezone rather than guessing one."""
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, TypeError) as err:
        raise ContractError("Invalid or timezone-less API timestamp") from err


def default_start(today: date) -> date:
    """Previous twelve calendar months, including leap-day handling."""
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return date(today.year - 1, 2, 28)


def earliest_start(today: date) -> date:
    """API's rolling calendar-year retention boundary."""
    return date(today.year - 5, 1, 1)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Local midnight boundaries can span 23, 24 or 25 hours."""
    return (
        datetime.combine(day, datetime.min.time(), DENMARK).astimezone(UTC),
        datetime.combine(
            day + timedelta(days=1), datetime.min.time(), DENMARK
        ).astimezone(UTC),
    )


@dataclass(frozen=True)
class Reading:
    """One normalized hourly quantity."""

    start: datetime
    kwh: Decimal | None
    quality: str


@dataclass
class MeterSeries:
    """Directions and non-fatal unsupported-data notices."""

    streams: dict[str, dict[datetime, Reading]]
    notices: set[str]


def parse_series(
    documents: list[dict[str, Any]], expected_meter: str | None = None
) -> MeterSeries:
    """Translate malformed nested responses into a sanitized contract error."""
    try:
        return _parse_series(documents, expected_meter)
    except (KeyError, TypeError, AttributeError, OverflowError) as err:
        raise ContractError("Malformed energy market document") from err


def _parse_series(
    documents: list[dict[str, Any]], expected_meter: str | None
) -> MeterSeries:
    """Merge periods/access windows, rejecting ambiguous overlapping streams."""
    streams: dict[str, dict[datetime, Reading]] = defaultdict(dict)
    raw: dict[tuple[str, datetime], tuple[Reading, timedelta, str]] = {}
    notices: set[str] = set()
    factors = {"KWH": Decimal(1), "WH": Decimal("0.001"), "MWH": Decimal(1000)}
    for document in documents:
        if not isinstance(document.get("TimeSeries"), list):
            raise ContractError("Missing time-series list")
        for series in document["TimeSeries"]:
            point_id = (series.get("MarketEvaluationPoint") or {}).get("mRID") or {}
            if (
                expected_meter
                and point_id.get("name")
                and point_id["name"] != expected_meter
            ):
                raise ContractError("Time series belongs to a different meter")
            business = series.get("businessType")
            direction = {
                "A01": "production",
                "A04": "consumption",
                "A64": "consumption",
            }.get(business)
            if direction is None:
                notices.add("unsupported_business_type")
                continue
            unit = str(series.get("measurement_Unit.name", "")).upper()
            if unit not in factors:
                raise ContractError("Unsupported energy unit")
            for period in series.get("Period") or []:
                resolution = {
                    "PT1H": timedelta(hours=1),
                    "PT15M": timedelta(minutes=15),
                }.get(period.get("resolution"))
                if resolution is None:
                    notices.add("unsupported_resolution")
                    continue
                start = timestamp(period["timeInterval"]["start"])
                end = timestamp(period["timeInterval"]["end"])
                if (
                    end <= start
                    or start.minute % 15
                    or start.second
                    or start.microsecond
                ):
                    raise ContractError("Invalid energy interval")
                for point in period.get("Point") or []:
                    try:
                        position = int(point["position"])
                        at = start + (position - 1) * resolution
                        quality = point["out_Quantity.quality"]
                        value = point.get("out_Quantity.quantity")
                        quantity = (
                            Decimal(str(value)) * factors[unit]
                            if value is not None
                            else None
                        )
                    except (ValueError, TypeError, KeyError, InvalidOperation) as err:
                        raise ContractError("Malformed energy point") from err
                    if position < 1 or at + resolution > end:
                        raise ContractError("Energy position outside period")
                    if quality not in {"A01", "A02", "A03", "A04", "A05"}:
                        raise ContractError("Unknown energy quality")
                    if quantity is not None and (
                        not quantity.is_finite() or quantity < 0
                    ):
                        raise ContractError("Invalid energy quantity")
                    if quality in {"A02", "A05"}:
                        quantity = None
                    elif quantity is None:
                        raise ContractError("Missing quantity for usable quality")
                    reading = Reading(at, quantity, quality)
                    key = (direction, at)
                    candidate = (reading, resolution, business)
                    if key in raw and raw[key] != candidate:
                        raise ContractError("Conflicting overlapping time series")
                    raw[key] = candidate
    quarters: dict[tuple[str, datetime], list[Reading]] = defaultdict(list)
    for (direction, at), (reading, resolution, _) in raw.items():
        if resolution == timedelta(hours=1):
            if at.minute:
                raise ContractError("Hourly reading is not hour-aligned")
            streams[direction][at] = reading
        else:
            quarters[(direction, at.replace(minute=0))].append(reading)
    for (direction, hour), readings in quarters.items():
        if hour in streams[direction]:
            raise ContractError("Mixed overlapping resolutions")
        complete = len(readings) == 4 and all(item.kwh is not None for item in readings)
        total = sum((item.kwh for item in readings if item.kwh is not None), Decimal(0))
        quality = "A03" if any(item.quality == "A03" for item in readings) else "A04"
        streams[direction][hour] = Reading(
            hour, total if complete else None, quality if complete else "A05"
        )
    return MeterSeries(dict(streams), notices)


def summary(
    readings: dict[datetime, Reading], start: datetime, end: datetime
) -> dict[str, Any]:
    """Return reported energy and explicit coverage for a half-open interval."""
    usable = [
        r for at, r in readings.items() if start <= at < end and r.kwh is not None
    ]
    return {
        "energy": float(sum((r.kwh for r in usable if r.kwh is not None), Decimal(0)))
        if usable
        else None,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "reported_hours": len(usable),
        "expected_hours": int((end - start).total_seconds() // 3600),
        "complete": len(usable) == int((end - start).total_seconds() // 3600),
        "estimated_hours": sum(r.quality == "A03" for r in usable),
    }
