"""Register map of the Neptun Modbus RTU module (addresses are 0-based, as in the vendor PDF)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

DEVICE_TYPE = 0xCB43

# --- coils (FC1 read, FC5/FC15 write) ---
COIL_LEAK = 0
COIL_VALVES = 1  # 1 = open, 0 = closed or closing
COIL_VALVE_FEEDBACK = 2
COIL_CLOSE_ON_LOW_UPS = 3
COIL_SIREN = 4
COIL_RELAY = 5  # writable only in relay mode MANUAL
COIL_CHILD_LOCK = 6
COIL_CLOSE_ON_SENSOR_LOSS = 7
COIL_BUTTON_LED = 8
COIL_COUNT = 9

# --- discrete inputs (FC2) ---
DI_VALVES_POWER = 0
DI_UPS_PRESENT = 1
DI_ON_UPS = 2
DI_COUNT = 3

# --- holding registers (FC3 read, FC6/FC16 write) ---
HR_SIREN_MINUTES = 2
HR_VALVE_POWER_TIMEOUT = 3
HR_WIRED_CONFIG = 4  # 4..6, lines 1..3
HR_WIRED_DIFF = 7  # 7..9
HR_PULSE_STEP = 0x0A  # 0x0A..0x0C
HR_PULSE_VALUE = 0x0D  # 0x0D..0x12, hi/lo word pairs
HR_MODE = 0x13
HR_FLOOR_WASH_LEFT = 0x14
HR_RADIO_FIRST = 0x15  # 0x15..0x46: radio sensors 11..60
HR_RELAY_MODE = 0x47
HR_RESET = 0x48
HR_BRIGHTNESS = 0x49
HR_COUNT = 0x4A  # read 0..0x49 in one request

RADIO_COUNT = 50
RADIO_FIRST_NUMBER = 11
WIRED_LINES = 3

# --- input registers (FC4) ---
IR_DEVICE_TYPE = 0
IR_HW_VERSION = 1
IR_FW_VERSION = 2
IR_VALVE_LINES = 3
IR_WIRED_STATE = 4
IR_WIRED_SAVED = 5  # 5..7
IR_ERRORS = 8
IR_UPS_PERCENT = 9
IR_COUNT = 10

# radio sensor register bits
RADIO_ADDED = 0x80
RADIO_LOST = 0x20
RADIO_LEAK = 0x10

# wired line config bits
WIRED_FEEDBACK = 0x80
WIRED_MODE_MASK = 0x7F

SIREN_ALWAYS = 241
VALVE_POWER_TIMEOUT_MIN = 60
VALVE_POWER_TIMEOUT_MAX = 600
BRIGHTNESS_MAX = 15


class OperatingMode(IntEnum):
    NORMAL = 0
    ADD_RADIO = 1
    FLOOR_WASH = 2


class RelayMode(IntEnum):
    OFF = 0
    BY_VALVES = 1
    BY_LEAK = 2
    MANUAL = 3


class WiredMode(IntEnum):
    SENSOR = 0
    BUTTON = 1
    TOGGLE = 2
    PULSE_COUNTER = 3
    UNUSED = 4


class ResetCommand(IntEnum):
    REBOOT = 1
    FACTORY_RESET = 2


# error bits of IR 8 -> (key, English description)
ERROR_BITS: dict[int, tuple[str, str]] = {
    0: ("short_modules_power", "Short circuit on modules power"),
    2: ("short_wired_power", "Short circuit on wired sensors power"),
    3: ("short_valves_power", "Short circuit on valves power"),
    4: ("valves_stuck", "Valves are stuck"),
    5: ("lora_unavailable", "LoRa chip unavailable"),
    6: ("eeprom_unavailable", "EEPROM unavailable"),
    7: ("ups_low", "Low UPS charge"),
}

# valve line state (IR 3): bit offset within the line byte -> state key
VALVE_STATE_BITS: dict[int, str] = {
    0: "normal",
    1: "open_circuit",
    2: "short",
    3: "stuck",
    4: "limit_timeout",
    5: "not_connected",
}
VALVE_STATE_PRIORITY = (2, 1, 3, 4, 5, 0)
VALVE_STATES = ["feedback_off", *VALVE_STATE_BITS.values()]


def decode_valve_line(ir3: int, line: int) -> str:
    """State key for a valve line (1 or 2) from IR 3."""
    byte = (ir3 >> (8 * (line - 1))) & 0xFF
    if byte & 0x3F == 0:
        return "feedback_off"
    for bit in VALVE_STATE_PRIORITY:
        if byte & (1 << bit):
            return VALVE_STATE_BITS[bit]
    return "feedback_off"


def decode_errors(mask: int) -> list[str]:
    """English descriptions of the set error bits."""
    return [text for bit, (_, text) in ERROR_BITS.items() if mask & (1 << bit)]


def decode_firmware(raw: int) -> str:
    """IR 2 low byte is xx.yy.zzzz (2 + 2 + 4 bits)."""
    raw &= 0xFF
    return f"{raw >> 6}.{(raw >> 4) & 0x3}.{raw & 0xF}"


def to_signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


@dataclass(frozen=True, slots=True)
class RadioSensor:
    """Decoded status register of one radio sensor."""

    number: int
    leak: bool
    lost: bool
    battery_level: int  # 0..3
    rssi: int  # 0..3

    @property
    def battery_percent(self) -> int:
        return round(self.battery_level * 100 / 3)


def decode_radio(index: int, raw: int) -> RadioSensor | None:
    """Return None when the sensor slot is not in use (bit 7 clear)."""
    if not raw & RADIO_ADDED:
        return None
    return RadioSensor(
        number=RADIO_FIRST_NUMBER + index,
        leak=bool(raw & RADIO_LEAK),
        lost=bool(raw & RADIO_LOST),
        battery_level=(raw >> 2) & 0x3,
        rssi=raw & 0x3,
    )


@dataclass(slots=True)
class Blocks:
    """Raw register blocks of one poll cycle. A block is None when it could not be read."""

    coils: list[bool] | None = None
    discrete: list[bool] | None = None
    holding: list[int] | None = None
    input: list[int] | None = None
    ok: dict[str, bool] = field(default_factory=dict)
