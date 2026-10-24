from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.neptun_modbus import config_flow
from custom_components.neptun_modbus.const import (
    CONF_BAUDRATE,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    CONF_TIMEOUT,
    CONF_VALVE_LINES,
    DOMAIN,
)

USER_INPUT = {CONF_PORT: "/dev/ttyUSB0", CONF_SLAVE: 1, CONF_BAUDRATE: 9600}


@pytest.fixture(autouse=True)
def port_present():
    with (
        patch.object(config_flow, "_port_error", return_value=None),
        patch.object(config_flow.os.path, "realpath", side_effect=lambda p: p),
    ):
        yield


async def start(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_user_flow(hass, module):
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == "/dev/ttyUSB0:1"


@pytest.mark.parametrize(
    ("setup_module", "error"),
    [
        (lambda m: setattr(m, "disconnected", True), "cannot_connect"),
        (lambda m: setattr(m, "silent", True), "timeout"),
        (lambda m: m.input.__setitem__(0, 0x1234), "not_neptun"),
        (lambda m: setattr(m, "exception_functions", {"read_input_registers"}), "cannot_connect"),
    ],
)
async def test_user_flow_errors_then_recovers(hass, module, setup_module, error):
    setup_module(module)
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    module.disconnected = False
    module.silent = False
    module.exception_functions = set()
    module.input[0] = 0xCB43
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_permission_error(hass, module):
    with patch.object(config_flow, "_port_error", return_value="permission"):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "permission"}


async def test_already_configured(hass, module, entry):
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass, setup):
    result = await hass.config_entries.options.async_init(setup.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 10, CONF_TIMEOUT: 2.0, CONF_RETRIES: 2, CONF_VALVE_LINES: "2"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup.options == {
        CONF_SCAN_INTERVAL: 10,
        CONF_TIMEOUT: 2.0,
        CONF_RETRIES: 2,
        CONF_VALVE_LINES: 2,
    }
    assert isinstance(setup.options[CONF_RETRIES], int)
    await hass.async_block_till_done(wait_background_tasks=True)
    # entry is reloaded: line 2 sensor appears and the poll interval changed
    assert hass.states.get("sensor.neptun_valve_line_2").state == "not_connected"
    assert setup.runtime_data.update_interval.total_seconds() == 10


async def test_reconfigure_releases_port_and_reloads(hass, setup, module):
    result = await setup.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    new = {CONF_PORT: "/dev/ttyUSB1", CONF_SLAVE: 2, CONF_BAUDRATE: 19200}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup.data == new
    assert setup.unique_id == "/dev/ttyUSB1:2"


async def test_reconfigure_error_keeps_entry(hass, setup, module):
    result = await setup.start_reconfigure_flow(hass)
    module.silent = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_SLAVE: 5}
    )
    assert result["errors"] == {"base": "timeout"}
    assert setup.data[CONF_SLAVE] == 1


async def test_address_from_selector_is_stored_as_int(hass, module):
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_SLAVE: 1.0, CONF_BAUDRATE: 9600}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert isinstance(result["data"][CONF_SLAVE], int)
    assert result["result"].unique_id == "/dev/ttyUSB0:1"
