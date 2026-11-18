"""Shared, bounded Energinet day-ahead price cache, independent of meter polling."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

from aiohttp import ClientError, ClientResponseError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DENMARK, DOMAIN
from .models import ContractError, day_bounds
from .pricing import FIRST_PRICE_DAY, Prices, prices_complete

_LOGGER = logging.getLogger(__name__)
URL = "https://api.energidataservice.dk/dataset/DayAheadPrices"
MARKET_KEY = f"{DOMAIN}_market"


def parse_prices(records: list[dict[str, Any]]) -> dict[str, Prices]:
    """TimeUTC is documented UTC despite its offset-less source encoding."""
    result: dict[str, Prices] = {"DK1": {}, "DK2": {}}
    try:
        for record in records:
            area = record["PriceArea"]
            if area not in result:
                raise ValueError
            at = datetime.fromisoformat(record["TimeUTC"])
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            at = at.astimezone(UTC)
            value = Decimal(str(record["DayAheadPriceDKK"])) / 1000
            if at.minute % 15 or at.second or at.microsecond or not value.is_finite():
                raise ValueError
            if at in result[area] and result[area][at] != value:
                raise ValueError
            result[area][at] = value
    except (ValueError, KeyError, TypeError, InvalidOperation) as err:
        raise ContractError("Invalid Danish market-price response") from err
    return result


class MarketCoordinator(DataUpdateCoordinator[dict[str, Prices]]):
    """One cache and publication schedule across all configured entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="El-Overblik HA market",
            update_interval=timedelta(minutes=5),
        )
        self.data = {"DK1": {}, "DK2": {}}
        self.owners: dict[str, Callable[[], set[date]]] = {}
        self.fetched_at: datetime | None = None
        self.error: str | None = None
        self._attempts: dict[date, datetime] = {}
        self._retry_at: datetime | None = None
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.market")

    async def load(self) -> None:
        if cached := await self._store.async_load():
            try:
                self.data = parse_prices(cached["records"])
                if cached.get("fetched_at"):
                    self.fetched_at = datetime.fromisoformat(cached["fetched_at"])
            except ContractError, KeyError, TypeError, ValueError:
                self.error = "invalid_cache"
                _LOGGER.error(
                    "Danish market-price cache is invalid; prices will be fetched again"
                )

    async def _async_update_data(self) -> dict[str, Prices]:
        now = datetime.now(UTC)
        local = now.astimezone(DENMARK)
        today = local.date()
        if self._retry_at and now < self._retry_at:
            raise UpdateFailed(
                "Danish market-price retry is waiting for its backoff deadline"
            )
        days = {today, today + timedelta(days=1)}
        for requested in self.owners.values():
            days.update(requested())
        days = {
            day
            for day in days
            if max(FIRST_PRICE_DAY, today - timedelta(days=31))
            <= day
            <= today + timedelta(days=1)
        }
        fetched = False
        try:
            for day in sorted(days):
                last = self._attempts.get(day)
                complete = all(prices_complete(self.data[a], day) for a in self.data)
                if complete and day < today:
                    continue
                publication = (
                    day == today + timedelta(days=1)
                    and 13 <= local.hour < 14
                    and not complete
                )
                if last and now - last < timedelta(minutes=5 if publication else 360):
                    continue
                if day > today and complete:
                    continue
                self._attempts[day] = now
                await self._fetch(day, now)
                fetched = True
        except (ClientError, TimeoutError, ContractError) as err:
            self._attempts.pop(day, None)
            self._retry_at = max(self._retry_at or now, now + timedelta(minutes=5))
            self.error = (
                "invalid_response"
                if isinstance(err, ContractError)
                else "rate_limited"
                if isinstance(err, ClientResponseError) and err.status == 429
                else "connection_error"
            )
            raise UpdateFailed(f"Danish market prices: {self.error}") from err
        if self.error and not fetched:
            raise UpdateFailed(f"Danish market prices: {self.error}; awaiting retry")
        self.error = None
        cutoff, _ = day_bounds(today - timedelta(days=31))
        for area in self.data:
            self.data[area] = {
                at: price for at, price in self.data[area].items() if at >= cutoff
            }
        self._attempts = {
            day: at for day, at in self._attempts.items() if day >= cutoff.date()
        }
        if not fetched:
            return self.data
        await self._store.async_save(
            {
                "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
                "records": [
                    {
                        "TimeUTC": at.isoformat(),
                        "PriceArea": area,
                        "DayAheadPriceDKK": str(price * 1000),
                    }
                    for area, prices in self.data.items()
                    for at, price in prices.items()
                ],
            }
        )
        return self.data

    async def _fetch(self, day: date, now: datetime) -> None:
        async with asyncio.timeout(30):
            async with async_get_clientsession(self.hass).get(
                URL,
                params={
                    "start": day.isoformat(),
                    "end": (day + timedelta(days=1)).isoformat(),
                    "filter": '{"PriceArea":["DK1","DK2"]}',
                    "columns": "TimeUTC,PriceArea,DayAheadPriceDKK",
                    "limit": "201",
                },
            ) as response:
                if response.status in {429, 503}:
                    retry = response.headers.get("Retry-After", "300")
                    try:
                        seconds = max(300, int(retry))
                    except ValueError:
                        try:
                            seconds = max(
                                300,
                                int(
                                    (parsedate_to_datetime(retry) - now).total_seconds()
                                ),
                            )
                        except TypeError, ValueError, OverflowError:
                            seconds = 300
                    self._retry_at = now + timedelta(seconds=seconds)
                response.raise_for_status()
                try:
                    document = await response.json()
                    records = document["records"]
                    if not isinstance(records, list) or len(records) > 200:
                        raise ValueError
                    parsed = parse_prices(records)
                    start, end = day_bounds(day)
                    if any(
                        not start <= at < end
                        for prices in parsed.values()
                        for at in prices
                    ):
                        raise ValueError
                except (KeyError, ValueError, TypeError) as err:
                    raise ContractError("Invalid Danish market-price response") from err
                for area, prices in parsed.items():
                    # Replace the requested day so upstream removals do not linger.
                    self.data[area] = {
                        at: price
                        for at, price in self.data[area].items()
                        if not start <= at < end
                    } | prices
                self.fetched_at = now
