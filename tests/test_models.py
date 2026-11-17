"""Data correctness, including quality, duplicates and Danish DST."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.eloverblik_data.models import (
    ContractError,
    Reading,
    day_bounds,
    default_start,
    parse_meters,
    parse_series,
    summary,
)
from custom_components.eloverblik_data.statistics import cumulative


def document(
    start="2026-01-01T00:00:00Z",
    resolution="PT1H",
    quantities=("1.25", "2.5"),
    qualities=None,
    business="A04",
    unit="KWH",
):
    at = datetime.fromisoformat(start)
    step = timedelta(minutes=15 if resolution == "PT15M" else 60)
    return {
        "TimeSeries": [
            {
                "businessType": business,
                "measurement_Unit.name": unit,
                "Period": [
                    {
                        "resolution": resolution,
                        "timeInterval": {
                            "start": start,
                            "end": (at + len(quantities) * step).isoformat(),
                        },
                        "Point": [
                            {
                                "position": str(index + 1),
                                "out_Quantity.quantity": value,
                                "out_Quantity.quality": (
                                    qualities[index] if qualities else "A04"
                                ),
                            }
                            for index, value in enumerate(quantities)
                        ],
                    }
                ],
            }
        ]
    }


def test_meter_normalization():
    assert parse_meters(
        " 001234567890123456,001234567890123457,001234567890123456, "
    ) == ["001234567890123456", "001234567890123457"]
    for invalid in (
        "",
        "123",
        "１２３４５６７８９０１２３４５６７８",
        "00123456789012345x",
    ):
        with pytest.raises(ValueError):
            parse_meters(invalid)
    assert default_start(date(2024, 2, 29)) == date(2023, 2, 28)


def test_quality_units_and_deduplication():
    doc = document(
        quantities=("1000", None, "2000"), qualities=("A03", "A02", "A05"), unit="WH"
    )
    values = parse_series([doc, doc]).streams["consumption"]
    assert [reading.kwh for reading in values.values()] == [Decimal(1), None, None]
    assert len(values) == 3
    with pytest.raises(ContractError, match="Conflicting"):
        parse_series([doc, document(quantities=("2",))])
    with pytest.raises(ContractError, match="Conflicting"):
        parse_series([document(), document(business="A64")])


def test_quarters_and_missing_values():
    stream = parse_series(
        [document(resolution="PT15M", quantities=("1", "2", "3", "4"))]
    ).streams["consumption"]
    assert next(iter(stream.values())).kwh == Decimal(10)
    stream = parse_series(
        [document(resolution="PT15M", quantities=("1", "2", "3"))]
    ).streams["consumption"]
    assert next(iter(stream.values())).kwh is None
    with pytest.raises(ContractError, match="unit"):
        parse_series([document(unit="m3")])
    assert parse_series([document(resolution="P1D")]).notices == {
        "unsupported_resolution"
    }


@pytest.mark.parametrize(
    ("day", "hours"), [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)]
)
def test_dst_summaries(day, hours):
    start, end = day_bounds(day)
    assert (end - start).total_seconds() == hours * 3600
    readings = {
        start + timedelta(hours=i): Reading(
            start + timedelta(hours=i), Decimal(1), "A04"
        )
        for i in range(hours)
    }
    assert summary(readings, start, end)["energy"] == hours
    assert summary(readings, start, end)["complete"]
    readings.pop(start)
    assert not summary(readings, start, end)["complete"]


def test_corrections_and_earlier_backfill():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    readings = {
        start + timedelta(hours=1): Reading(
            start + timedelta(hours=1), Decimal(2), "A04"
        ),
        start + timedelta(hours=2): Reading(
            start + timedelta(hours=2), Decimal(3), "A04"
        ),
    }
    assert [r["sum"] for r in cumulative(readings)] == [2, 5]
    readings[start] = Reading(start, Decimal(1), "A04")
    readings[start + timedelta(hours=1)] = Reading(
        start + timedelta(hours=1), Decimal("0.5"), "A03"
    )
    assert [r["sum"] for r in cumulative(readings)] == [1, 1.5, 4.5]
    readings[start] = Reading(start, None, "A02")
    assert [r["sum"] for r in cumulative(readings)] == [0.5, 3.5]


@pytest.mark.parametrize("quantity", ["NaN", "Infinity", "-1", "bad"])
def test_invalid_quantities(quantity):
    with pytest.raises(ContractError):
        parse_series([document(quantities=(quantity,))])
