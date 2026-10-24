"""Constants for the Neptun Modbus integration."""

from homeassistant.const import Platform

DOMAIN = "neptun_modbus"

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.VALVE,
]

CONF_PORT = "port"
CONF_SLAVE = "slave"
CONF_BAUDRATE = "baudrate"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"
CONF_RETRIES = "retries"
CONF_VALVE_LINES = "valve_lines"

DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_SLAVE = 1
DEFAULT_BAUDRATE = 9600
DEFAULT_SCAN_INTERVAL = 5
DEFAULT_TIMEOUT = 1.0
DEFAULT_RETRIES = 2
DEFAULT_VALVE_LINES = 1

BAUDRATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

# consecutive failed cycles before entities become unavailable
FAIL_THRESHOLD = 3
# cycles without bit 7 before a radio sensor device is removed
RADIO_REMOVE_AFTER = 3
# seconds without a link before a Repairs issue is raised
ISSUE_AFTER = 300

ISSUE_NO_CONNECTION = "no_connection"

SERVICE_FACTORY_RESET = "factory_reset"
SERVICE_FORGET_RADIO = "forget_radio_sensor"
