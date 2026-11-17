"""Read-only, throttled asynchronous Customer API client."""

import asyncio
import math
import time
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import API_URL
from .models import (
    ApiError,
    AuthenticationError,
    ContractError,
    EndpointUnavailableError,
)


class RequestGate:
    """Shared across entries; keep well below the per-IP limits."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.next_token = 0.0

    async def wait(self, *, token: bool = False) -> None:
        """Space all calls and allow at most two token exchanges per minute."""
        async with self.lock:
            await asyncio.sleep(
                max(
                    0,
                    self.next_request - time.monotonic(),
                    (self.next_token - time.monotonic()) if token else 0,
                )
            )
            self.next_request = time.monotonic() + 1.0
            if token:
                self.next_token = time.monotonic() + 31.0


def retry_delay(value: str | None) -> float:
    """Honor Retry-After seconds or HTTP dates, never less than one minute."""
    if not value:
        return 60
    try:
        seconds = float(value)
        return max(60, seconds) if math.isfinite(seconds) else 60
    except ValueError:
        try:
            return max(60, parsedate_to_datetime(value).timestamp() - time.time())
        except ValueError, TypeError, OverflowError:
            return 60


class CustomerApi:
    """Only GET and read-only POST operations are implemented."""

    def __init__(
        self, session: ClientSession, refresh_token: str, gate: RequestGate
    ) -> None:
        self.session = session
        self.refresh_token = refresh_token
        self.gate = gate
        self._token: str | None = None
        self._expires = 0.0
        self._token_lock = asyncio.Lock()

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        body: dict[str, Any] | None = None,
        *,
        exchange: bool = False,
    ) -> dict[str, Any]:
        for attempt in range(3):
            await self.gate.wait(token=exchange)
            try:
                async with self.session.request(
                    method,
                    f"{API_URL}/{path}",
                    headers={"Authorization": f"Bearer {token}", "api-version": "1.0"},
                    json=body,
                    timeout=ClientTimeout(total=60),
                ) as response:
                    if response.status in {401, 403}:
                        raise AuthenticationError("API authentication rejected")
                    if response.status == 404:
                        raise EndpointUnavailableError(
                            "The live API does not expose this endpoint"
                        )
                    if response.status in {429, 503}:
                        if attempt == 2:
                            raise ApiError(
                                f"API temporarily unavailable (HTTP {response.status})"
                            )
                        await asyncio.sleep(
                            retry_delay(response.headers.get("Retry-After"))
                        )
                        continue
                    if response.status != 200:
                        raise ApiError(f"API request failed (HTTP {response.status})")
                    payload = await response.json(content_type=None)
                    if not isinstance(payload, dict) or "result" not in payload:
                        raise ContractError("Unexpected API response envelope")
                    return payload
            except (ClientError, TimeoutError) as err:
                raise ApiError("Unable to reach ElOverblik") from err
            except ValueError as err:
                raise ContractError("Invalid API JSON") from err
        raise ApiError("API retries exhausted")

    async def access_token(self) -> str:
        async with self._token_lock:
            if self._token is None or time.monotonic() >= self._expires:
                response = await self._request(
                    "GET", "token", self.refresh_token, exchange=True
                )
                if not isinstance(response["result"], str) or not response["result"]:
                    raise AuthenticationError("Invalid token response")
                self._token = response["result"]
                self._expires = time.monotonic() + 23.9 * 3600
            return self._token

    async def request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> Any:
        token = await self.access_token()
        try:
            return (await self._request(method, path, token, body))["result"]
        except AuthenticationError:
            async with self._token_lock:
                if self._token == token:
                    self._token = None
            return (await self._request(method, path, await self.access_token(), body))[
                "result"
            ]

    async def linked_meters(self) -> list[dict[str, Any]]:
        result = await self.request(
            "GET", "meteringpoints/meteringpoints?includeAll=false"
        )
        if not isinstance(result, list) or not all(
            isinstance(item, dict) for item in result
        ):
            raise ContractError("Invalid meter list")
        return result

    @staticmethod
    def body(meters: list[str]) -> dict[str, Any]:
        return {"meteringPoints": {"meteringPoint": meters}}

    async def batch(self, endpoint: str, meters: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index in range(0, len(meters), 10):
            value = await self.request(
                "POST", endpoint, self.body(meters[index : index + 10])
            )
            if not isinstance(value, list) or not all(
                isinstance(item, dict) for item in value
            ):
                raise ContractError("Invalid batch response")
            results.extend(value)
        return results

    async def timeseries(
        self, meters: list[str], start: date, end: date
    ) -> list[dict[str, Any]]:
        if not start < end or (end - start).days > 730:
            raise ValueError("Time-series window must be between 1 and 730 days")
        return await self.batch(f"meterdata/gettimeseries/{start}/{end}/Hour", meters)

    async def details(self, meters: list[str]) -> list[dict[str, Any]]:
        return await self.batch("meteringpoints/meteringpoint/getdetails", meters)

    async def charges(self, meters: list[str]) -> list[dict[str, Any]]:
        return await self.batch("meteringpoints/meteringpoint/getcharges", meters)

    async def dated_charges(
        self, meters: list[str], start: datetime, end: datetime
    ) -> dict[str, Any]:
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or not start < end
            or end - start > timedelta(days=31)
        ):
            raise ValueError(
                "Charge queries require aware timestamps and at most 31 days"
            )
        if len(meters) > 10:
            raise ValueError("Charge queries support at most 10 meters per action")
        result = await self.request(
            "POST",
            "meteringpoints/meteringpoint/getchargelinkswithcharges",
            {
                "query": [
                    {
                        "meteringPointId": meter,
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                    }
                    for meter in meters
                ],
            },
        )
        if not isinstance(result, dict):
            raise ContractError("Invalid dated charges response")
        return result
