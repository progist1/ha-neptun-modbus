"""Setup, states and availability through the real Home Assistant core."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.neptun_modbus.const import DOMAIN, FAIL_THRESHOLD


def state(hass, entity_id):
    s = hass.states.get(entity_id)
    assert s is not None, entity_id
    return s.state


async def test_setup_snapshot_states(hass, setup):
    assert setup.state is ConfigEntryState.LOADED
    assert state(hass, "binary_sensor.neptun_leak") == STATE_OFF
    assert state(hass, "binary_sensor.neptun_valves_power") == STATE_OFF
    assert state(hass, "binary_sensor.neptun_ups_present") == STATE_ON
    assert state(hass, "binary_sensor.neptun_running_on_ups") == STATE_OFF
    assert state(hass, "binary_sensor.neptun_connection") == STATE_ON
    assert state(hass, "binary_sensor.neptun_problem") == STATE_OFF
    assert state(hass, "valve.neptun_valves") == "open"
    assert state(hass, "sensor.neptun_ups_charge") == "100"
    assert state(hass, "sensor.neptun_firmware_version") == "0.2.0"
    assert state(hass, "sensor.neptun_valve_line_1") == "normal"
    assert hass.states.get("sensor.neptun_valve_line_2") is None  # one line configured
    assert state(hass, "switch.neptun_valve_line_feedback") == STATE_ON
    assert state(hass, "switch.neptun_button_backlight") == STATE_ON
    assert state(hass, "switch.neptun_child_lock") == STATE_OFF
    assert state(hass, "number.neptun_led_brightness") == "15"
    assert state(hass, "number.neptun_siren_duration") == "10"
    assert state(hass, "number.neptun_valves_power_timeout") == "120"
    assert state(hass, "select.neptun_relay_mode") == "off"
    assert state(hass, "select.neptun_operating_mode") == "normal"
    assert state(hass, "select.neptun_wired_line_1_mode") == "sensor"
    assert state(hass, "switch.neptun_wired_line_1_feedback") == STATE_ON


async def test_radio_devices_from_snapshot(hass, setup):
    devices = dr.async_get(hass)
    radios = [
        d
        for d in dr.async_entries_for_config_entry(devices, setup.entry_id)
        if d.model == "Radio leak sensor"
    ]
    assert sorted(d.name for d in radios) == [f"Neptun radio sensor {n}" for n in (11, 12, 13, 14)]
    main = devices.async_get_device_by_identifier((DOMAIN, setup.entry_id), setup.entry_id)
    assert all(d.via_device_id == main.id for d in radios)
    assert state(hass, "binary_sensor.neptun_radio_sensor_11_leak") == STATE_OFF
    assert state(hass, "binary_sensor.neptun_radio_sensor_11_lost") == STATE_OFF
    assert state(hass, "sensor.neptun_radio_sensor_11_battery") == "100"
    assert state(hass, "sensor.neptun_radio_sensor_14_signal_level") == "2"


async def test_unique_ids(hass, setup):
    entries = er.async_entries_for_config_entry(er.async_get(hass), setup.entry_id)
    assert len(entries) > 60
    ids = [e.unique_id for e in entries]
    assert all(ids) and len(ids) == len(set(ids))


async def test_leak_and_errors(hass, setup, module):
    module.coils[0] = True
    module.set_radio(12, 0x8D | 0x10)
    module.input[8] = 0b10001000  # valves short + low UPS
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "binary_sensor.neptun_leak") == STATE_ON
    assert state(hass, "binary_sensor.neptun_radio_sensor_12_leak") == STATE_ON
    assert state(hass, "binary_sensor.neptun_problem") == STATE_ON
    assert hass.states.get("binary_sensor.neptun_problem").attributes["errors"] == [
        "Short circuit on valves power",
        "Low UPS charge",
    ]
    assert state(hass, "binary_sensor.neptun_short_circuit_on_valves_power") == STATE_ON
    assert state(hass, "binary_sensor.neptun_ups_charge_low") == STATE_ON


async def test_lost_radio_dry_is_unknown_not_dry(hass, setup, module):
    # no news from a sensor is not the same as "no water"
    module.set_radio(13, 0x8D | 0x20)
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "binary_sensor.neptun_radio_sensor_13_lost") == STATE_ON
    assert state(hass, "binary_sensor.neptun_radio_sensor_13_leak") == STATE_UNAVAILABLE


async def test_lost_radio_that_was_leaking_stays_on(hass, setup, module):
    module.set_radio(13, 0x8D | 0x20 | 0x10)
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "binary_sensor.neptun_radio_sensor_13_leak") == STATE_ON


async def test_wrong_device_type(hass, entry, module):
    module.input[0] = 0x1234
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_port_missing_retries(hass, entry, module):
    module.disconnected = True
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_silent_module_retries(hass, entry, module):
    module.silent = True
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_transient_glitch_keeps_values(hass, setup, module):
    coordinator = setup.runtime_data
    module.silent = True
    for _ in range(FAIL_THRESHOLD - 1):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state(hass, "valve.neptun_valves") == "open"
        assert state(hass, "binary_sensor.neptun_connection") == STATE_ON
    module.silent = False
    await coordinator.async_refresh()
    assert coordinator.consecutive_failures == 0


async def test_link_loss_and_recovery(hass, setup, module):
    coordinator = setup.runtime_data
    module.silent = True
    for _ in range(FAIL_THRESHOLD):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "binary_sensor.neptun_connection") == STATE_OFF
    assert state(hass, "sensor.neptun_consecutive_failed_polls") == str(FAIL_THRESHOLD)
    assert state(hass, "valve.neptun_valves") == STATE_UNAVAILABLE
    assert state(hass, "binary_sensor.neptun_leak") == STATE_UNAVAILABLE
    assert state(hass, "binary_sensor.neptun_radio_sensor_11_leak") == STATE_UNAVAILABLE
    assert state(hass, "switch.neptun_child_lock") == STATE_UNAVAILABLE
    module.silent = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "binary_sensor.neptun_connection") == STATE_ON
    assert state(hass, "valve.neptun_valves") == "open"


async def test_partial_block_failure(hass, setup, module):
    module.silent_functions = {"read_holding_registers"}
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    # holding based entities go away, the rest stays
    assert state(hass, "select.neptun_relay_mode") == STATE_UNAVAILABLE
    assert state(hass, "switch.neptun_child_lock") == STATE_OFF  # coils still readable
    assert state(hass, "number.neptun_led_brightness") == STATE_UNAVAILABLE
    assert state(hass, "binary_sensor.neptun_radio_sensor_11_leak") == STATE_UNAVAILABLE
    assert state(hass, "valve.neptun_valves") == "open"
    assert state(hass, "binary_sensor.neptun_leak") == STATE_OFF
    assert state(hass, "sensor.neptun_ups_charge") == "100"
    assert state(hass, "binary_sensor.neptun_connection") == STATE_ON


async def test_radio_discovery_and_removal(hass, setup, module):
    coordinator = setup.runtime_data
    devices = dr.async_get(hass)

    def radio_names():
        return {
            d.name
            for d in dr.async_entries_for_config_entry(devices, setup.entry_id)
            if d.model == "Radio leak sensor"
        }

    module.set_radio(20, 0x8F)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "Neptun radio sensor 20" in radio_names()
    assert state(hass, "sensor.neptun_radio_sensor_20_battery") == "100"

    # one missed cycle must not remove it
    module.set_radio(20, 0)
    await coordinator.async_refresh()
    module.set_radio(20, 0x8F)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "Neptun radio sensor 20" in radio_names()

    module.set_radio(20, 0)
    for _ in range(3):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "Neptun radio sensor 20" not in radio_names()
    assert hass.states.get("sensor.neptun_radio_sensor_20_battery") is None

    # and it can come back
    module.set_radio(20, 0x8F)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "Neptun radio sensor 20" in radio_names()


async def test_unload(hass, setup):
    assert await hass.config_entries.async_unload(setup.entry_id)
    await hass.async_block_till_done()
    assert setup.state is ConfigEntryState.NOT_LOADED


async def test_no_deprecated_device_registry_usage(hass, entry, caplog):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert "deprecated" not in caplog.text.lower()
    assert "via_device" not in caplog.text


def wired_devices(hass, entry):
    return sorted(
        d.name
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if d.model == "Wired input line"
    )


async def test_wired_line_devices_follow_line_mode(hass, setup, module):
    coordinator = setup.runtime_data
    assert wired_devices(hass, setup) == [f"Neptun wired line {n}" for n in (1, 2, 3)]
    main = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, setup.entry_id), setup.entry_id
    )
    line1 = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{setup.entry_id}_wired_1"), setup.entry_id
    )
    assert line1.via_device_id == main.id
    assert state(hass, "binary_sensor.neptun_wired_line_1_state") == STATE_OFF
    assert state(hass, "switch.neptun_wired_line_2_feedback") == STATE_ON

    # "not used" removes the line device and its entities, the mode select stays on the main device
    module.holding[5] = 4
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert wired_devices(hass, setup) == ["Neptun wired line 1", "Neptun wired line 3"]
    assert hass.states.get("binary_sensor.neptun_wired_line_2_state") is None
    assert hass.states.get("switch.neptun_wired_line_2_feedback") is None
    assert state(hass, "select.neptun_wired_line_2_mode") == "unused"

    # ...and selecting a mode again brings it back
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.neptun_wired_line_2_mode", "option": "sensor"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert wired_devices(hass, setup) == [f"Neptun wired line {n}" for n in (1, 2, 3)]
    assert state(hass, "binary_sensor.neptun_wired_line_2_state") == STATE_OFF


async def test_wired_line_leak(hass, setup, module):
    module.input[4] = 0b001  # line 1
    await setup.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "binary_sensor.neptun_wired_line_1_state") == STATE_ON
    assert state(hass, "binary_sensor.neptun_wired_line_2_state") == STATE_OFF
    assert (
        hass.states.get("binary_sensor.neptun_wired_line_1_state").attributes["device_class"]
        == "moisture"
    )


async def test_dead_module_costs_one_block_per_cycle(hass, setup, module):
    coordinator = setup.runtime_data
    module.silent = True
    before = coordinator.client.stats.requests
    await coordinator.async_refresh()
    # coils is tried (retries attempts), the other three blocks are skipped
    assert coordinator.client.stats.requests - before == 2
    assert coordinator.block_errors["input"] is not None


async def test_degraded_link_is_visible(hass, setup, module):
    coordinator = setup.runtime_data
    module.silent_functions = {"read_holding_registers"}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.link_state == "degraded"
    assert coordinator.last_error  # not wiped by the other blocks that answered
    assert state(hass, "sensor.neptun_link_state") == "degraded"
    assert state(hass, "binary_sensor.neptun_connection") == STATE_ON
    attrs = hass.states.get("sensor.neptun_link_state").attributes
    assert "holding" in attrs and "coils" not in attrs
    module.silent_functions = set()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "sensor.neptun_link_state") == "connected"
    assert coordinator.last_error is None


async def test_link_state_disconnected(hass, setup, module):
    coordinator = setup.runtime_data
    module.silent = True
    for _ in range(FAIL_THRESHOLD):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "sensor.neptun_link_state") == "disconnected"


async def test_unload_and_set_up_again_on_same_port(hass, setup, module):
    assert await hass.config_entries.async_unload(setup.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(setup.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "valve.neptun_valves") == "open"
