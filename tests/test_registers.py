from custom_components.neptun_modbus.registers import (
    decode_errors,
    decode_firmware,
    decode_radio,
    decode_valve_line,
    to_signed16,
)


def test_firmware():
    assert decode_firmware(0x6C) == "1.2.12"
    assert decode_firmware(0x20) == "0.2.0"  # real module


def test_radio_snapshot_values():
    first = decode_radio(0, 0x8D)
    assert first.number == 11
    assert (first.leak, first.lost, first.battery_level, first.rssi) == (False, False, 3, 1)
    assert first.battery_percent == 100
    assert decode_radio(3, 0x8E).rssi == 2


def test_radio_bits():
    r = decode_radio(0, 0x80 | 0x20 | 0x10 | 0b0100 | 0b11)
    assert (r.leak, r.lost, r.battery_level, r.rssi) == (True, True, 1, 3)
    assert r.battery_percent == 33


def test_radio_not_added():
    assert decode_radio(0, 0x00) is None
    assert decode_radio(0, 0x7F) is None  # bit 7 decides


def test_valve_lines_snapshot():
    # real module: line 1 normal, line 2 not connected
    assert decode_valve_line(0x2001, 1) == "normal"
    assert decode_valve_line(0x2001, 2) == "not_connected"


def test_valve_line_priority_and_feedback_off():
    assert decode_valve_line(0, 1) == "feedback_off"
    assert decode_valve_line(0b000110, 1) == "short"  # short beats open circuit
    assert decode_valve_line(0b001010, 1) == "open_circuit"  # open circuit beats stuck


def test_errors():
    assert decode_errors(0) == []
    assert decode_errors(0b10001001) == [
        "Short circuit on modules power",
        "Short circuit on valves power",
        "Low UPS charge",
    ]
    assert decode_errors(0b10) == []  # bit 1 unused


def test_signed():
    assert to_signed16(0xFFFF) == -1
    assert to_signed16(5) == 5
