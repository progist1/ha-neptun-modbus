"""Writes: what is sent to the module and how the UI reflects what the module accepted."""

import pytest
import voluptuous as vol
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.neptun_modbus.const import DOMAIN


async def call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


def state(hass, entity_id):
    return hass.states.get(entity_id).state


async def test_valve_close_open(hass, setup, module):
    await call(hass, "valve", "close_valve", "valve.neptun_valves")
    assert module.coils[1] is False
    assert state(hass, "valve.neptun_valves") == "closed"
    await call(hass, "valve", "open_valve", "valve.neptun_valves")
    assert module.coils[1] is True
    assert state(hass, "valve.neptun_valves") == "open"


async def test_coil_switches(hass, setup, module):
    await call(hass, "switch", "turn_on", "switch.neptun_child_lock")
    assert module.coils[6] is True
    await call(hass, "switch", "turn_off", "switch.neptun_button_backlight")
    assert module.coils[8] is False
    assert state(hass, "switch.neptun_button_backlight") == "off"
    await call(hass, "switch", "turn_off", "switch.neptun_close_valves_on_low_ups")
    await call(hass, "switch", "turn_on", "switch.neptun_close_valves_on_sensor_loss")
    await call(hass, "switch", "turn_off", "switch.neptun_valve_line_feedback")
    assert module.coils[3:4] == [False] and module.coils[7] is True and module.coils[2] is False


async def test_relay_only_in_manual_mode(hass, setup, module):
    assert state(hass, "switch.neptun_relay") == STATE_UNAVAILABLE
    await call(
        hass, "select", SERVICE_SELECT_OPTION, "select.neptun_relay_mode", **{ATTR_OPTION: "manual"}
    )
    assert module.holding[0x47] == 3
    await call(hass, "switch", "turn_on", "switch.neptun_relay")
    assert module.coils[5] is True
    assert state(hass, "switch.neptun_relay") == "on"


async def test_numbers(hass, setup, module):
    await call(hass, "number", SERVICE_SET_VALUE, "number.neptun_led_brightness", **{ATTR_VALUE: 7})
    assert module.holding[0x49] == 7
    await call(
        hass, "number", SERVICE_SET_VALUE, "number.neptun_siren_duration", **{ATTR_VALUE: 241}
    )
    assert module.holding[2] == 241
    await call(
        hass, "number", SERVICE_SET_VALUE, "number.neptun_valves_power_timeout", **{ATTR_VALUE: 300}
    )
    assert module.holding[3] == 300


@pytest.mark.parametrize(
    ("entity", "value"),
    [
        ("number.neptun_led_brightness", 16),
        ("number.neptun_valves_power_timeout", 59),
        ("number.neptun_valves_power_timeout", 601),
        ("number.neptun_siren_duration", 242),
    ],
)
async def test_out_of_range_never_reaches_module(hass, setup, module, entity, value):
    with pytest.raises(ServiceValidationError):
        await call(hass, "number", SERVICE_SET_VALUE, entity, **{ATTR_VALUE: value})
    assert [w for w in module.log if w[0] == "register"] == []


async def test_pulse_counter_value_is_32_bit(hass, setup, module):
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = "number.neptun_wired_line_2_pulse_counter_value"
    assert hass.states.get(entity_id) is None  # disabled by default
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(setup.entry_id)
    await hass.async_block_till_done()
    await call(
        hass,
        "number",
        SERVICE_SET_VALUE,
        entity_id,
        **{ATTR_VALUE: 70000},
    )
    assert module.holding[0x0F:0x11] == [1, 70000 - 65536]


async def test_operating_mode(hass, setup, module):
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        "select.neptun_operating_mode",
        **{ATTR_OPTION: "add_radio"},
    )
    assert module.holding[0x13] == 1
    assert state(hass, "select.neptun_operating_mode") == "add_radio"


async def test_wired_mode_preserves_and_drops_feedback(hass, setup, module):
    # sensor + feedback (0x80) -> button: the module has no feedback bit outside sensor mode
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        "select.neptun_wired_line_1_mode",
        **{ATTR_OPTION: "button"},
    )
    assert module.holding[4] == 1
    assert state(hass, "switch.neptun_wired_line_1_feedback") == STATE_UNAVAILABLE
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        "select.neptun_wired_line_1_mode",
        **{ATTR_OPTION: "sensor"},
    )
    assert module.holding[4] == 0
    await call(hass, "switch", "turn_on", "switch.neptun_wired_line_1_feedback")
    assert module.holding[4] == 0x80
    await call(hass, "switch", "turn_off", "switch.neptun_wired_line_1_feedback")
    assert module.holding[4] == 0


async def test_buttons(hass, setup, module):
    module.coils[0] = True
    module.coils[4] = True
    await setup.runtime_data.async_refresh()
    await call(hass, "button", SERVICE_PRESS, "button.neptun_reset_leak")
    assert module.coils[0] is False and module.coils[4] is False
    assert state(hass, "binary_sensor.neptun_leak") == "off"

    await call(hass, "button", SERVICE_PRESS, "button.neptun_wired_line_2_save_sensor_count")
    assert ("register", 8, 0) in module.log
    assert ("register", 7, 0) not in module.log  # only that line


async def test_dangerous_buttons_disabled_by_default(hass, setup):
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for entity_id in (
        "button.neptun_reboot_module",
        "button.neptun_radio_sensor_11_remove_sensor",
    ):
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None


async def test_factory_reset_requires_confirm(hass, setup, module):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "factory_reset", {"confirm": False}, blocking=True)
    assert module.last_reset_command is None
    await hass.services.async_call(DOMAIN, "factory_reset", {"confirm": True}, blocking=True)
    assert module.last_reset_command == 2


async def test_forget_radio_service(hass, setup, module):
    await hass.services.async_call(DOMAIN, "forget_radio_sensor", {"number": 14}, blocking=True)
    assert module.holding[0x18] == 0
    with pytest.raises(vol.Invalid):  # out of 11..60
        await hass.services.async_call(DOMAIN, "forget_radio_sensor", {"number": 10}, blocking=True)


async def test_write_failure_is_reported(hass, setup, module):
    module.silent_functions = {"write_coil"}
    with pytest.raises(HomeAssistantError):
        await call(hass, "valve", "close_valve", "valve.neptun_valves")
    assert module.coils[1] is True
