"""Fetch linked-meter data and run resumable, read-only history jobs."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CustomerApi
from .const import (
    CONF_ALL_HISTORY,
    CONF_HISTORY,
    CONF_METERS,
    CONF_POLL,
    DENMARK,
    DOMAIN,
    METADATA_FIELDS,
    NAME,
)
from .models import (
    ApiError,
    AuthenticationError,
    ContractError,
    default_start,
    earliest_start,
    parse_series,
)
from .statistics import MeterHistory

_LOGGER = logging.getLogger(__name__)
ACCESS_ERRORS = {20010, 20012, 30010, 30016, 40014}


@dataclass
class MeterData:
    """Public meter state; intentionally excludes personal master-data fields."""

    history: MeterHistory
    details: dict[str, Any] = field(default_factory=dict)
    charges: dict[str, Any] = field(default_factory=dict)
    last_success: datetime | None = None
    error: str | None = None
    metadata_errors: dict[str, int | str] = field(default_factory=dict)
    notices: set[str] = field(default_factory=set)


class Coordinator(DataUpdateCoordinator[dict[str, MeterData]]):
    """Share one schedule and one history job per entry."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: CustomerApi
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=NAME,
            update_interval=timedelta(hours=entry.options.get(CONF_POLL, 6)),
        )
        self.entry = entry
        self.api = api
        self.meters = list(entry.data[CONF_METERS])
        self.states = {
            meter: MeterData(MeterHistory(hass, meter)) for meter in self.meters
        }
        self._lock = asyncio.Lock()
        self._metadata_at: datetime | None = None
        self._reconciled_at: datetime | None = None
        self._job: asyncio.Task[None] | None = None
        self.ready_for_statistics = False
        self.dated_charges_available: bool | None = None
        self.job_status: dict[str, Any] = {"status": "idle"}
        self._cache: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.entry.{entry.entry_id}"
        )

    async def load(self) -> None:
        for state in self.states.values():
            await state.history.load()
        if cache := await self._cache.async_load():
            self._metadata_at = (
                datetime.fromisoformat(cache["metadata_at"])
                if cache.get("metadata_at")
                else None
            )
            self._reconciled_at = (
                datetime.fromisoformat(cache["reconciled_at"])
                if cache.get("reconciled_at")
                else None
            )
            for meter, data in cache.get("meters", {}).items():
                if not isinstance(meter, str) or meter not in self.states:
                    continue
                state = self.states[meter]
                state.details = data.get("details", {})
                state.charges = data.get("charges", {})
                state.metadata_errors = data.get("metadata_errors", {})
                if data.get("last_success"):
                    state.last_success = datetime.fromisoformat(data["last_success"])

    def history_start(self) -> date:
        today = datetime.now(DENMARK).date()
        if self.entry.options.get(CONF_ALL_HISTORY):
            return earliest_start(today)
        configured = self.entry.options.get(CONF_HISTORY)
        if configured is None:
            configured = min(
                (
                    state.history.history_start
                    for state in self.states.values()
                    if state.history.history_start
                ),
                default=None,
            )
        return max(
            earliest_start(today),
            date.fromisoformat(configured) if configured else default_start(today),
        )

    def _issue(self, meter: str, code: int | None) -> None:
        issue_id = f"access_{meter}"
        if code in ACCESS_ERRORS:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="meter_access",
                translation_placeholders={"meter": meter[-4:]},
            )
        elif code is None:
            if not any(
                value in ACCESS_ERRORS
                for value in self.states[meter].metadata_errors.values()
            ):
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _metadata(self, now: datetime) -> None:
        for kind, results in (
            ("details", await self.api.details(self.meters)),
            ("charges", await self.api.charges(self.meters)),
        ):
            seen: set[str] = set()
            for item in results:
                meter = item.get("id")
                if not isinstance(meter, str) or meter not in self.states:
                    continue
                seen.add(meter)
                state = self.states[meter]
                if not item.get("success"):
                    code = item.get("errorCode")
                    state.metadata_errors[kind] = (
                        code if isinstance(code, int) else "unknown_error"
                    )
                    self._issue(meter, code)
                    continue
                result = item.get("result")
                if not isinstance(result, dict):
                    raise ContractError("Invalid metadata result")
                state.metadata_errors.pop(kind, None)
                if kind == "details":
                    state.details = {
                        key: result[key] for key in METADATA_FIELDS if key in result
                    }
                else:
                    charges: dict[str, Any] = {}
                    fields = {
                        "priceId",
                        "name",
                        "description",
                        "owner",
                        "validFromDate",
                        "validToDate",
                        "periodType",
                        "price",
                        "prices",
                        "quantity",
                    }
                    for kind_key in ("tariffs", "subscriptions", "fees"):
                        values = result.get(kind_key) or []
                        if not isinstance(values, list) or not all(
                            isinstance(value, dict) for value in values
                        ):
                            raise ContractError("Invalid reported charges")
                        charges[kind_key] = [
                            {
                                key: value
                                for key, value in charge.items()
                                if key in fields
                            }
                            for charge in values
                        ]
                    state.charges = charges
            for meter in set(self.meters) - seen:
                self.states[meter].metadata_errors[kind] = "missing_response"
        self._metadata_at = now

    async def fetch_energy(self, meters: list[str], start: date, end: date) -> set[str]:
        responses = await self.api.timeseries(meters, start, end)
        documents: dict[str, list[dict[str, Any]]] = {}
        failed: set[str] = set()
        for response in responses:
            meter = response.get("id")
            if meter not in meters:
                raise ContractError("Unexpected meter in time-series response")
            state = self.states[meter]
            if not response.get("success"):
                code = response.get("errorCode")
                state.error = "no_data" if code == 30015 else f"api_{code}"
                self._issue(meter, code)
                if code != 30015:
                    failed.add(meter)
                documents.setdefault(meter, [])
                continue
            document = response.get("MyEnergyData_MarketDocument")
            if not isinstance(document, dict):
                raise ContractError("Missing energy market document")
            documents.setdefault(meter, []).append(document)
        succeeded: set[str] = set()
        for meter in meters:
            state = self.states[meter]
            if meter not in documents:
                state.error = "missing_response"
                continue
            if meter in failed:
                continue
            try:
                parsed = parse_series(documents[meter], meter)
            except ContractError as err:
                state.error = "api_contract"
                _LOGGER.warning("Invalid metering-point response: %s", err)
                continue
            # Restrict overlapping API date boundaries to the requested local dates.
            streams = {
                direction: {
                    at: value
                    for at, value in values.items()
                    if start <= at.astimezone(DENMARK).date() < end
                    and at + timedelta(hours=1) <= datetime.now(UTC)
                }
                for direction, values in parsed.streams.items()
            }
            await state.history.merge(streams)
            state.notices = parsed.notices
            state.last_success = datetime.now(UTC)
            state.error = None if documents[meter] else "no_data"
            self._issue(meter, None)
            succeeded.add(meter)
        return succeeded

    async def _async_update_data(self) -> dict[str, MeterData]:
        try:
            async with self._lock:
                now = datetime.now(UTC)
                today = now.astimezone(DENMARK).date()
                if self._metadata_at is None or now - self._metadata_at >= timedelta(
                    days=1
                ):
                    await self._metadata(now)
                if not self.ready_for_statistics:
                    return self.states
                weekly = (
                    self._reconciled_at is None
                    or now - self._reconciled_at >= timedelta(days=7)
                )
                start = max(
                    self.history_start(), today - timedelta(days=90 if weekly else 14)
                )
                for cursor in range(0, (today + timedelta(days=1) - start).days, 31):
                    begin = start + timedelta(days=cursor)
                    await self.fetch_energy(
                        self.meters,
                        begin,
                        min(begin + timedelta(days=31), today + timedelta(days=1)),
                    )
                if weekly:
                    self._reconciled_at = now
                await self._cache.async_save(
                    {
                        "metadata_at": self._metadata_at.isoformat()
                        if self._metadata_at
                        else None,
                        "reconciled_at": self._reconciled_at.isoformat()
                        if self._reconciled_at
                        else None,
                        "meters": {
                            meter: {
                                "details": state.details,
                                "charges": state.charges,
                                "metadata_errors": state.metadata_errors,
                                "last_success": state.last_success.isoformat()
                                if state.last_success
                                else None,
                            }
                            for meter, state in self.states.items()
                        },
                    }
                )
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            raise UpdateFailed(str(err)) from err
        if self.ready_for_statistics and (
            self._job is None
            or self._job.done()
            and self.job_status["status"] == "error"
        ):
            self.start_history()
        return self.states

    async def initial_update(self) -> None:
        """Recorder cannot acknowledge imports until HA has finished startup."""
        self.ready_for_statistics = True
        for state in self.states.values():
            if state.history.dirty:
                await state.history.import_statistics(rebuild=True)
        await self.async_refresh()

    def start_history(
        self, start: date | None = None, end: date | None = None
    ) -> dict[str, Any]:
        if self._job and not self._job.done():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="history_busy"
            )
        today = datetime.now(DENMARK).date()
        begin, finish = start or self.history_start(), end or today + timedelta(days=1)
        if not earliest_start(today) <= begin < finish <= today + timedelta(days=1):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_period"
            )
        self.job_status = {
            "job_id": uuid4().hex,
            "status": "running",
            "start": begin.isoformat(),
            "end": finish.isoformat(),
        }
        self._job = self.entry.async_create_background_task(
            self.hass,
            self._history_job(begin, finish, resume=start is None),
            f"{NAME} history",
            eager_start=False,
        )
        return dict(self.job_status)

    async def _history_job(self, start: date, end: date, *, resume: bool) -> None:
        try:
            failures = 0
            for meter, state in self.states.items():
                history = state.history
                cursor = start
                if (
                    resume
                    and history.history_start
                    and date.fromisoformat(history.history_start) <= start
                    and history.checkpoint
                ):
                    cursor = max(start, date.fromisoformat(history.checkpoint))
                while cursor < end:
                    finish = min(cursor + timedelta(days=31), end)
                    async with self._lock:
                        succeeded = await self.fetch_energy([meter], cursor, finish)
                        if meter not in succeeded:
                            failures += 1
                            _LOGGER.warning(
                                "Historical import for a meter stopped; check its data status and access period"
                            )
                            break
                        if resume:
                            history.history_start = start.isoformat()
                            history.checkpoint = finish.isoformat()
                            await history.save()
                    cursor = finish
                    self.job_status["completed_through"] = cursor.isoformat()
                    self.async_set_updated_data(self.states)
                    await asyncio.sleep(0)
            self.job_status["status"] = "error" if failures else "complete"
            self.job_status["failed_meter_count"] = failures
        except AuthenticationError:
            self.job_status.update(status="error", error="invalid_auth")
            self.entry.async_start_reauth(self.hass)
        except ApiError as err:
            self.job_status.update(status="error", error=str(err))
            _LOGGER.warning("%s historical import failed: %s", NAME, err)
        except asyncio.CancelledError:
            self.job_status["status"] = "cancelled"
            raise
        finally:
            self.async_set_updated_data(self.states)
