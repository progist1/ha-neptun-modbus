"""Shared fixtures."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neptun_modbus import client as client_module
from custom_components.neptun_modbus.const import CONF_BAUDRATE, CONF_PORT, CONF_SLAVE, DOMAIN

from .fake_module import FakeClient, FakeModule

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch):
    monkeypatch.setattr(client_module, "RETRY_PAUSE", 0)


@pytest.fixture
def module() -> FakeModule:
    return FakeModule()


@pytest.fixture(autouse=True)
def patched_client(module, monkeypatch):
    monkeypatch.setattr(
        client_module,
        "AsyncModbusSerialClient",
        lambda port, **kwargs: FakeClient(module, port, **kwargs),
    )
    return module


@pytest.fixture
def entry_data() -> dict:
    return {CONF_PORT: "/dev/ttyUSB0", CONF_SLAVE: 1, CONF_BAUDRATE: 9600}


@pytest.fixture
def entry(hass, entry_data) -> MockConfigEntry:
    e = MockConfigEntry(domain=DOMAIN, data=entry_data, unique_id="/dev/ttyUSB0:1", title="Neptun")
    e.add_to_hass(hass)
    return e


@pytest.fixture
async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
