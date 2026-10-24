"""Config flow."""

from __future__ import annotations

import glob
import os
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .client import NeptunClient, NeptunConnectionError, NeptunProtocolError, NeptunTimeoutError
from .const import (
    BAUDRATES,
    CONF_BAUDRATE,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    CONF_TIMEOUT,
    CONF_VALVE_LINES,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DEFAULT_TIMEOUT,
    DEFAULT_VALVE_LINES,
    DOMAIN,
)
from .coordinator import NeptunConfigEntry
from .registers import DEVICE_TYPE, IR_DEVICE_TYPE


def _list_ports() -> list[str]:
    ports = sorted(glob.glob("/dev/serial/by-id/*"))
    ports += sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    return ports


def _port_error(port: str) -> str | None:
    if not os.path.exists(port):
        return "cannot_connect"
    if not os.access(port, os.R_OK | os.W_OK):
        return "permission"
    return None


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> str | None:
    """Open the port and check that a Neptun module answers. Returns an error key or None."""
    if (error := await hass.async_add_executor_job(_port_error, data[CONF_PORT])) is not None:
        return error
    client = NeptunClient(data[CONF_PORT], data[CONF_SLAVE], data[CONF_BAUDRATE])
    try:
        await client.connect()
        device_type = (await client.read_input_registers(IR_DEVICE_TYPE, 1))[0]
    except NeptunTimeoutError:
        return "timeout"
    except NeptunConnectionError, NeptunProtocolError:
        return "cannot_connect"
    finally:
        await client.close()
    return None if device_type == DEVICE_TYPE else "not_neptun"


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Selectors return floats; the port, address and baud rate are stored as str/int/int."""
    return {
        CONF_PORT: user_input[CONF_PORT],
        CONF_SLAVE: int(user_input[CONF_SLAVE]),
        CONF_BAUDRATE: int(user_input[CONF_BAUDRATE]),
    }


def _connection_schema(ports: list[str], defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): SelectSelector(
                SelectSelectorConfig(
                    options=ports or [DEFAULT_PORT],
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_SLAVE, default=defaults.get(CONF_SLAVE, DEFAULT_SLAVE)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_BAUDRATE, default=defaults.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
            ): vol.In(BAUDRATES),
        }
    )


class NeptunConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize(user_input)
            real = await self.hass.async_add_executor_job(os.path.realpath, user_input[CONF_PORT])
            await self.async_set_unique_id(f"{real}:{user_input[CONF_SLAVE]}")
            self._abort_if_unique_id_configured()
            if (error := await _validate(self.hass, user_input)) is None:
                return self.async_create_entry(title="Neptun", data=user_input)
            errors["base"] = error
        ports = await self.hass.async_add_executor_job(_list_ports)
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(ports, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize(user_input)
            runtime = getattr(entry, "runtime_data", None)
            if runtime is not None:
                # only one process may own the port: stop the poller from reopening it while probing
                await runtime.client.pause()
            try:
                error = await _validate(self.hass, user_input)
            finally:
                if runtime is not None:
                    runtime.client.resume()
            if error is None:
                real = await self.hass.async_add_executor_job(
                    os.path.realpath, user_input[CONF_PORT]
                )
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=f"{real}:{user_input[CONF_SLAVE]}",
                    data_updates=user_input,
                )
            errors["base"] = error
        ports = await self.hass.async_add_executor_job(_list_ports)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(ports, user_input or dict(entry.data)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: NeptunConfigEntry) -> NeptunOptionsFlow:
        return NeptunOptionsFlow()


class NeptunOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # selectors return floats and strings
            user_input[CONF_VALVE_LINES] = int(user_input[CONF_VALVE_LINES])
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            user_input[CONF_RETRIES] = int(user_input[CONF_RETRIES])
            user_input[CONF_TIMEOUT] = float(user_input[CONF_TIMEOUT])
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=2, max=60, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_TIMEOUT, default=o.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): (
                    NumberSelector(
                        NumberSelectorConfig(
                            min=0.5,
                            max=5,
                            step=0.1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                ),
                vol.Required(CONF_RETRIES, default=o.get(CONF_RETRIES, DEFAULT_RETRIES)): (
                    NumberSelector(
                        NumberSelectorConfig(min=1, max=5, step=1, mode=NumberSelectorMode.BOX)
                    )
                ),
                vol.Required(
                    CONF_VALVE_LINES, default=str(o.get(CONF_VALVE_LINES, DEFAULT_VALVE_LINES))
                ): SelectSelector(
                    SelectSelectorConfig(options=["1", "2"], mode=SelectSelectorMode.LIST)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
