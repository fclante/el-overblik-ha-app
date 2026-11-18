"""Exercise native Home Assistant setup and translated error paths."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.eloverblik_data.const import (
    CONF_ALL_HISTORY,
    CONF_DASHBOARD,
    CONF_HISTORY,
    CONF_METER_SETTINGS,
    CONF_METERS,
    CONF_POLL,
    CONF_TOKEN,
    DENMARK,
    DOMAIN,
    NAME,
)
from custom_components.eloverblik_data.models import AuthenticationError

from .conftest import make_entry

METER = "001234567890123456"


async def test_setup_and_normalization(hass, api_mock):
    with patch(
        "custom_components.eloverblik_data.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TOKEN: "synthetic-token", CONF_METERS: f" {METER}, {METER} "},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == NAME
        assert result["data"][CONF_METERS] == [METER]
        await hass.async_block_till_done()


async def test_invalid_meter_and_auth(hass, api_mock):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "synthetic-token", CONF_METERS: "123"}
    )
    assert result["errors"] == {"base": "invalid_meters"}
    api_mock.linked_meters.side_effect = AuthenticationError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "synthetic-token", CONF_METERS: METER}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_missing_relation_and_duplicate_entry(hass, api_mock):
    api_mock.linked_meters.return_value = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "synthetic-token", CONF_METERS: METER}
    )
    assert result["errors"] == {"base": "missing_relation"}
    entry = make_entry()
    with patch(
        "custom_components.eloverblik_data.async_setup_entry", return_value=True
    ):
        await hass.config_entries.async_add(entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "synthetic-token", CONF_METERS: METER}
    )
    assert result["errors"] == {"base": "overlapping_meters"}


async def test_options_validate_history_and_use_native_language(hass, api_mock):
    entry = make_entry()
    with patch(
        "custom_components.eloverblik_data.async_setup_entry", return_value=True
    ):
        await hass.config_entries.async_add(entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ALL_HISTORY: False,
            CONF_HISTORY: "2010-01-01",
            CONF_POLL: 6,
        },
    )
    assert result["errors"] == {CONF_HISTORY: "invalid_date"}
    with patch("custom_components.eloverblik_data._reload", new_callable=AsyncMock):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_ALL_HISTORY: False,
                CONF_HISTORY: datetime.now(DENMARK).date().isoformat(),
                CONF_POLL: 3,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_POLL] == 3
    assert "language" not in entry.options


async def test_reauthentication_replaces_token_without_changing_meters(hass, api_mock):
    entry = make_entry()
    with patch(
        "custom_components.eloverblik_data.async_setup_entry", return_value=True
    ):
        await hass.config_entries.async_add(entry)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TOKEN: "synthetic-replacement", CONF_METERS: METER}
        )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_METERS] == [METER]
    assert entry.data[CONF_TOKEN] == "synthetic-replacement"


async def test_per_meter_price_options_validate_and_preserve_history(hass, api_mock):
    old_contract = {
        "area": "DK1",
        "contract": "fixed",
        "rate": "1.25",
        "vat_included": True,
        "effective": "2026-01-01",
    }
    entry = make_entry(options={CONF_METER_SETTINGS: {METER: old_contract}})
    with patch(
        "custom_components.eloverblik_data.async_setup_entry", return_value=True
    ):
        await hass.config_entries.async_add(entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ALL_HISTORY: True,
            CONF_HISTORY: "2026-01-01",
            CONF_POLL: 12,
            CONF_DASHBOARD: False,
            "configure_prices": True,
        },
    )
    assert result["step_id"] == "meter"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**old_contract, "rate": "NaN", "area": "none"}
    )
    assert result["errors"]["rate"] == "invalid_rate"
    assert result["errors"]["area"] == "choose_area"
    assert result["errors"]["effective"] == "new_effective_date"
    with patch("custom_components.eloverblik_data._reload", new_callable=AsyncMock):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {**old_contract, "rate": "-0.1", "effective": "2026-11-18"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_METER_SETTINGS][METER]["rate"] == "-0.1"
    assert entry.options[CONF_POLL] == 12
    assert entry.options[CONF_DASHBOARD] is False
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch("custom_components.eloverblik_data._reload", new_callable=AsyncMock):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_ALL_HISTORY: True,
                CONF_HISTORY: "2026-01-01",
                CONF_POLL: 6,
            },
        )
    assert entry.options[CONF_METER_SETTINGS][METER]["rate"] == "-0.1"
