"""Verify exact API payloads, bounded retries, batching and token lifecycle."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.eloverblik_data.api import CustomerApi, RequestGate, retry_delay
from custom_components.eloverblik_data.models import (
    ApiError,
    AuthenticationError,
    EndpointUnavailableError,
)


def response(payload=None, status=200, headers=None):
    result = MagicMock()
    result.status = status
    result.headers = headers or {}
    result.json = AsyncMock(return_value=payload)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=result)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


def client(responses):
    session = MagicMock()
    session.request.side_effect = responses
    gate = RequestGate()
    gate.wait = AsyncMock()
    return CustomerApi(session, "synthetic-refresh", gate)


async def test_cached_token_and_exact_batch_shape():
    api = client(
        [
            response({"result": "synthetic-access"}),
            response({"result": []}),
            response({"result": []}),
            response({"result": []}),
        ]
    )
    meters = [f"{i:018d}" for i in range(11)]
    await api.timeseries(meters, date(2026, 1, 1), date(2026, 2, 1))
    await api.linked_meters()
    calls = api.session.request.call_args_list
    assert len(calls) == 4
    assert calls[0].kwargs["headers"]["Authorization"] == "Bearer synthetic-refresh"
    assert calls[1].kwargs["json"] == {"meteringPoints": {"meteringPoint": meters[:10]}}
    assert calls[2].kwargs["json"] == {"meteringPoints": {"meteringPoint": meters[10:]}}
    assert calls[1].args[1].endswith("/2026-01-01/2026-02-01/Hour")


async def test_refresh_once_on_401_and_never_log_credentials():
    api = client(
        [
            response({"result": "old"}),
            response(status=401),
            response({"result": "new"}),
            response({"result": []}),
        ]
    )
    assert await api.linked_meters() == []
    assert api.session.request.call_count == 4
    api = client([response(status=401)])
    with pytest.raises(AuthenticationError, match="authentication"):
        await api.linked_meters()
    assert api.session.request.call_count == 1


async def test_rate_limit_retry_minimum_and_limit():
    api = client(
        [
            response({"result": "token"}),
            response(status=429, headers={"Retry-After": "5"}),
            response(status=503, headers={"Retry-After": "120"}),
            response(status=503),
        ]
    )
    with patch(
        "custom_components.eloverblik_data.api.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        with pytest.raises(ApiError, match="temporarily"):
            await api.linked_meters()
    assert [call.args[0] for call in sleep.call_args_list] == [60, 120]
    assert retry_delay("not-a-date") == 60


async def test_shared_gate_limits_requests_and_token_exchanges():
    now = [0.0]

    async def advance(seconds):
        now[0] += seconds

    gate = RequestGate()
    with (
        patch(
            "custom_components.eloverblik_data.api.time.monotonic",
            side_effect=lambda: now[0],
        ),
        patch(
            "custom_components.eloverblik_data.api.asyncio.sleep", side_effect=advance
        ),
    ):
        await asyncio.gather(gate.wait(token=True), gate.wait(token=True), gate.wait())
    assert now[0] >= 32


async def test_period_limit_before_network():
    api = client([])
    with pytest.raises(ValueError):
        await api.timeseries(["001234567890123456"], date(2020, 1, 1), date(2026, 1, 1))
    api.session.request.assert_not_called()


async def test_documented_but_unavailable_endpoint_is_explicit():
    api = client([response({"result": "token"}), response(status=404)])
    with pytest.raises(EndpointUnavailableError, match="does not expose"):
        await api.request(
            "POST",
            "meteringpoints/meteringpoint/getchargelinkswithcharges",
            {"query": []},
        )
    assert api.session.request.call_count == 2
