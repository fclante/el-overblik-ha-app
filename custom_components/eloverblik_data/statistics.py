"""Durable canonical quantities and correction-aware recorder imports."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .models import Reading, timestamp


def cumulative(readings: dict[datetime, Reading]) -> list[StatisticData]:
    """Rebase all later points after earlier additions or corrections."""
    total = Decimal(0)
    result: list[StatisticData] = []
    for at, reading in sorted(readings.items()):
        if reading.kwh is None:
            continue
        total += reading.kwh
        result.append(StatisticData(start=at, state=float(total), sum=float(total)))
    return result


class MeterHistory:
    """Persist per meter, not per token or entry, including removed meters."""

    def __init__(self, hass: HomeAssistant, meter: str) -> None:
        self.hass = hass
        self.meter = meter
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{meter}")
        self.streams: dict[str, dict[datetime, Reading]] = {}
        self.checkpoint: str | None = None
        self.history_start: str | None = None
        self.dirty = False

    async def load(self) -> None:
        if data := await self.store.async_load():
            self.checkpoint = data.get("checkpoint")
            self.history_start = data.get("history_start")
            for direction, values in data.get("streams", {}).items():
                self.streams[direction] = {
                    timestamp(at): Reading(
                        timestamp(at),
                        Decimal(quantity) if quantity is not None else None,
                        quality,
                    )
                    for at, quantity, quality in values
                }
            self.dirty = data.get("dirty", False)

    async def save(self) -> None:
        await self.store.async_save(
            {
                "checkpoint": self.checkpoint,
                "history_start": self.history_start,
                "dirty": self.dirty,
                "streams": {
                    direction: [
                        [
                            at.isoformat(),
                            str(r.kwh) if r.kwh is not None else None,
                            r.quality,
                        ]
                        for at, r in sorted(values.items())
                    ]
                    for direction, values in self.streams.items()
                },
            }
        )

    async def merge(self, streams: dict[str, dict[datetime, Reading]]) -> None:
        """Commit a replayable intent before touching recorder."""
        changed = [
            at
            for direction, values in streams.items()
            for at, value in values.items()
            if self.streams.get(direction, {}).get(at) != value
        ]
        if not changed and not self.dirty:
            return
        removed = self.dirty or any(
            value.kwh is None
            and (old := self.streams.get(direction, {}).get(at)) is not None
            and old.kwh is not None
            for direction, values in streams.items()
            for at, value in values.items()
        )
        for direction, values in streams.items():
            self.streams.setdefault(direction, {}).update(values)
        self.dirty = True
        await self.save()
        await self.import_statistics(
            rebuild=removed, from_time=min(changed) if changed and not removed else None
        )

    async def import_statistics(
        self, *, rebuild: bool = False, from_time: datetime | None = None
    ) -> None:
        recorder = get_instance(self.hass)
        for direction, values in self.streams.items():
            statistic_id = f"{DOMAIN}:{self.meter}_{direction}"
            if rebuild:
                recorder.async_clear_statistics([statistic_id])
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"ElOverblik {self.meter} {direction}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_class="energy",
                unit_of_measurement="kWh",
            )
            points = [
                point
                for point in cumulative(values)
                if from_time is None or point["start"] >= from_time
            ]
            for offset in range(0, len(points), 1000):
                async_add_external_statistics(
                    self.hass, metadata, points[offset : offset + 1000]
                )
        await recorder.async_block_till_done()
        self.dirty = False
        await self.save()
