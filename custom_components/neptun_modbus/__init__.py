"""Neptun Modbus integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .client import NeptunClient, NeptunConnectionError, NeptunError
from .const import (
    CONF_BAUDRATE,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SLAVE,
    CONF_TIMEOUT,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PLATFORMS,
    SERVICE_FACTORY_RESET,
    SERVICE_FORGET_RADIO,
)
from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import async_register_main_device
from .registers import (
    DEVICE_TYPE,
    HR_RADIO_FIRST,
    HR_RESET,
    IR_DEVICE_TYPE,
    RADIO_COUNT,
    RADIO_FIRST_NUMBER,
    ResetCommand,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_BASE = {vol.Optional("config_entry_id"): cv.string}
FACTORY_RESET_SCHEMA = vol.Schema({**SERVICE_BASE, vol.Required("confirm"): cv.boolean})
FORGET_RADIO_SCHEMA = vol.Schema(
    {
        **SERVICE_BASE,
        vol.Required("number"): vol.All(
            vol.Coerce(int),
            vol.Range(min=RADIO_FIRST_NUMBER, max=RADIO_FIRST_NUMBER + RADIO_COUNT - 1),
        ),
    }
)


def _coordinator_for(hass: HomeAssistant, call: ServiceCall) -> NeptunCoordinator:
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.runtime_data is not None and call.data.get("config_entry_id") in (None, e.entry_id)
    ]
    if len(entries) != 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def factory_reset(call: ServiceCall) -> None:
        if call.data["confirm"] is not True:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="confirm_required"
            )
        coordinator = _coordinator_for(hass, call)
        _LOGGER.warning("factory reset of the Neptun module requested")
        await coordinator.async_write_register(HR_RESET, int(ResetCommand.FACTORY_RESET))

    async def forget_radio(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call)
        index = call.data["number"] - RADIO_FIRST_NUMBER
        await coordinator.async_write_register(HR_RADIO_FIRST + index, 0)

    hass.services.async_register(
        DOMAIN, SERVICE_FACTORY_RESET, factory_reset, schema=FACTORY_RESET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORGET_RADIO, forget_radio, schema=FORGET_RADIO_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NeptunConfigEntry) -> bool:
    client = NeptunClient(
        entry.data[CONF_PORT],
        entry.data[CONF_SLAVE],
        entry.data[CONF_BAUDRATE],
        timeout=entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
        retries=entry.options.get(CONF_RETRIES, DEFAULT_RETRIES),
    )
    try:
        await client.connect()
        device_type = (await client.read_input_registers(IR_DEVICE_TYPE, 1))[0]
    except NeptunConnectionError as err:
        await client.close()
        raise ConfigEntryNotReady(f"Cannot open {entry.data[CONF_PORT]}: {err}") from err
    except NeptunError as err:
        await client.close()
        raise ConfigEntryNotReady(f"Module does not answer: {err}") from err
    if device_type != DEVICE_TYPE:
        await client.close()
        raise ConfigEntryError(f"Unexpected device type 0x{device_type:04X}")

    coordinator = NeptunCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.close()
        raise
    entry.runtime_data = coordinator
    _remove_obsolete_entities(hass, entry)
    entry.async_on_unload(client.close)
    async_register_main_device(hass, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_obsolete_entities(hass: HomeAssistant, entry: NeptunConfigEntry) -> None:
    """Drop entities of earlier versions that no longer exist (one button for all lines)."""
    registry = er.async_get(hass)
    for entity_id in [
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id == f"{entry.entry_id}_save_wired_count"
    ]:
        registry.async_remove(entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: NeptunConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
