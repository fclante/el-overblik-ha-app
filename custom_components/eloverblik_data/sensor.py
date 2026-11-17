"""Historical summaries, metadata, source-reported charges and diagnostics."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_utc_time_change

from . import EloverblikEntry
from .const import DENMARK
from .coordinator import ACCESS_ERRORS, Coordinator
from .entity import MeterEntity
from .models import day_bounds, summary


async def async_setup_entry(
    hass: HomeAssistant, entry: EloverblikEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    created: set[tuple[str, str]] = set()

    @callback
    def discover() -> None:
        entities: list[SensorEntity] = []
        for meter, data in coordinator.states.items():
            for key in (
                "last_success",
                "latest_measurement",
                "status",
                "import_status",
            ):
                if (meter, key) not in created:
                    created.add((meter, key))
                    entities.append(StatusSensor(coordinator, meter, key))
            for key in (
                "estimatedAnnualVolume",
                "powerLimitKW",
                "powerLimitA",
                "mpCapacity",
            ):
                present = (
                    data.details.get(key) is not None
                    or key == "powerLimitKW"
                    and data.details.get("powerLimitKWDecimal") is not None
                )
                if present and (meter, key) not in created:
                    created.add((meter, key))
                    entities.append(MetadataSensor(coordinator, meter, key))
            for direction in data.history.streams:
                for period in ("latest", "day", "month", "year"):
                    key = f"{direction}_{period}"
                    if (meter, key) not in created:
                        created.add((meter, key))
                        entities.append(
                            EnergySensor(coordinator, meter, direction, period)
                        )
            for kind in ("tariffs", "subscriptions", "fees"):
                for charge in data.charges.get(kind, []):
                    key = charge_key(kind, charge)
                    if (meter, key) not in created:
                        created.add((meter, key))
                        entities.append(ChargeSensor(coordinator, meter, kind, key))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class EnergySensor(MeterEntity, SensorEntity):
    """Snapshots have no state class: recorder imports own the energy history."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"

    def __init__(
        self, coordinator: Coordinator, meter: str, direction: str, period: str
    ) -> None:
        super().__init__(coordinator, meter, f"{direction}_{period}")
        self.direction, self.period = direction, period

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_utc_time_change(self.hass, self._tick, minute=0, second=0)
        )

    @callback
    def _tick(self, now: datetime) -> None:
        self.async_write_ha_state()

    def _value(self) -> dict[str, Any]:
        readings = self.meter_data.history.streams[self.direction]
        usable = [r for r in readings.values() if r.kwh is not None]
        if not usable:
            return {"energy": None}
        latest = max(usable, key=lambda r: r.start)
        now = datetime.now(DENMARK)
        if self.period == "latest":
            return {
                "energy": float(latest.kwh) if latest.kwh is not None else None,
                "period_start": latest.start.isoformat(),
                "period_end": (latest.start + timedelta(hours=1)).isoformat(),
                "quality": latest.quality,
            }
        if self.period == "day":
            counts: dict[Any, int] = {}
            for reading in usable:
                day = reading.start.astimezone(DENMARK).date()
                counts[day] = counts.get(day, 0) + 1
            days = sorted(
                {r.start.astimezone(DENMARK).date() for r in usable}, reverse=True
            )
            for day in days:
                start, end = day_bounds(day)
                if end <= now.astimezone(UTC) and counts[day] == int(
                    (end - start).total_seconds() // 3600
                ):
                    result = summary(readings, start, end)
                    if result["complete"]:
                        return result
            return {"energy": None, "complete": False}
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if self.period == "year":
            start = start.replace(month=1)
        result = summary(
            readings,
            start.astimezone(UTC),
            now.astimezone(UTC).replace(minute=0, second=0, microsecond=0),
        )
        result["covered_through"] = (latest.start + timedelta(hours=1)).isoformat()
        return result

    @property
    def native_value(self) -> float | None:
        return self._value()["energy"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {key: value for key, value in self._value().items() if key != "energy"}


class StatusSensor(MeterEntity, SensorEntity):
    """Timestamps and explicit import/source status."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: Coordinator, meter: str, key: str) -> None:
        super().__init__(coordinator, meter, key)
        self.key = key
        if key in {"last_success", "latest_measurement"}:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = (
                ["idle", "running", "complete", "error", "cancelled"]
                if key == "import_status"
                else [
                    "ready",
                    "limited",
                    "connection_error",
                    "no_data",
                    "access_error",
                    "api_error",
                    "missing_response",
                ]
            )

    @property
    def native_value(self) -> datetime | str | None:
        if self.key == "last_success":
            return self.meter_data.last_success
        if self.key == "latest_measurement":
            values = [
                at + timedelta(hours=1)
                for values in self.meter_data.history.streams.values()
                for at, reading in values.items()
                if reading.kwh is not None
            ]
            return max(values) if values else None
        if self.key == "import_status":
            return self.coordinator.job_status["status"]
        if not self.coordinator.last_update_success:
            return "connection_error"
        error = self.meter_data.error
        if error is None and self.meter_data.metadata_errors:
            return (
                "access_error"
                if any(
                    code in ACCESS_ERRORS
                    for code in self.meter_data.metadata_errors.values()
                )
                else "api_error"
            )
        if error and error.startswith("api_"):
            return (
                "access_error"
                if error in {f"api_{code}" for code in ACCESS_ERRORS}
                else "api_error"
            )
        return error or ("limited" if self.meter_data.notices else "ready")

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if self.key == "import_status":
            return self.coordinator.job_status
        if self.key == "status":
            return {
                **self.meter_data.details,
                "error_code": self.meter_data.error,
                "metadata_errors": self.meter_data.metadata_errors,
                "notices": sorted(self.meter_data.notices),
                "cost_status": "unsupported_semantics",
                "dated_charges_available": self.coordinator.dated_charges_available,
            }
        return None


class MetadataSensor(MeterEntity, SensorEntity):
    """Optional numeric fields retain their source-provided units."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: Coordinator, meter: str, key: str) -> None:
        super().__init__(coordinator, meter, key)
        self.key = key
        self._attr_translation_key = {
            "estimatedAnnualVolume": "estimated_annual_volume",
            "powerLimitKW": "power_limit_kw",
            "powerLimitA": "power_limit_a",
            "mpCapacity": "capacity",
        }[key]
        # Capacity has no unambiguous unit in the Customer API schema.
        self._attr_native_unit_of_measurement = {
            "estimatedAnnualVolume": {"KWH": "kWh", "MWH": "MWh", "WH": "Wh"}.get(
                str(
                    self.meter_data.details.get("energyTimeSeriesMeasureUnit", "")
                ).upper()
            ),
            "powerLimitKW": "kW",
            "powerLimitA": "A",
        }.get(key)

    @property
    def native_value(self) -> str | int | float | None:
        if (
            self.key == "powerLimitKW"
            and self.meter_data.details.get("powerLimitKWDecimal") is not None
        ):
            return self.meter_data.details["powerLimitKWDecimal"]
        return self.meter_data.details.get(self.key)


def charge_key(kind: str, charge: dict[str, Any]) -> str:
    """Include validity to distinguish concurrently returned revisions."""
    return f"{kind}_{charge.get('owner')}_{charge.get('priceId')}_{charge.get('validFromDate')}"


class ChargeSensor(MeterEntity, SensorEntity):
    """Source-reported amounts, never an inferred total bill or current rate."""

    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: Coordinator, meter: str, kind: str, key: str
    ) -> None:
        super().__init__(coordinator, meter, key)
        self.kind, self.key = kind, key
        self._attr_translation_key = (
            "reported_tariff" if kind == "tariffs" else "reported_fixed_charge"
        )
        if charge := self._charge():
            self._attr_translation_placeholders = {
                "charge": charge.get("name") or charge.get("priceId") or kind
            }
        if kind != "tariffs":
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = "DKK"
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["source_reported"]

    def _charge(self) -> dict[str, Any] | None:
        return next(
            (
                charge
                for charge in self.meter_data.charges.get(self.kind, [])
                if charge_key(self.kind, charge) == self.key
            ),
            None,
        )

    @property
    def available(self) -> bool:
        return (
            self._charge() is not None
            and self.coordinator.last_update_success
            and "charges" not in self.meter_data.metadata_errors
        )

    @property
    def native_value(self) -> str | float | None:
        charge = self._charge()
        if charge is None:
            return None
        return "source_reported" if self.kind == "tariffs" else charge.get("price")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if charge := self._charge():
            return {
                key: charge[key]
                for key in (
                    "priceId",
                    "owner",
                    "description",
                    "validFromDate",
                    "validToDate",
                    "periodType",
                    "quantity",
                )
                if key in charge
            } | {
                "interpretation": "source_reported_not_total_cost",
                "current_rate_available": False,
            }
        return None
