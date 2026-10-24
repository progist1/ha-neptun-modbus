"""Sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_VALVE_LINES, DEFAULT_VALVE_LINES
from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import (
    NeptunEntity,
    NeptunLinkEntity,
    NeptunRadioEntity,
    NeptunWiredEntity,
    async_add_radio_entities,
    async_add_wired_entities,
)
from .registers import (
    HR_PULSE_VALUE,
    HR_WIRED_DIFF,
    IR_ERRORS,
    IR_FW_VERSION,
    IR_HW_VERSION,
    IR_UPS_PERCENT,
    IR_VALVE_LINES,
    VALVE_STATES,
    Blocks,
    decode_errors,
    decode_firmware,
    decode_valve_line,
    to_signed16,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NeptunSensorDescription(SensorEntityDescription):
    block: str
    value_fn: Callable[[Blocks], Any]
    attrs_fn: Callable[[Blocks], dict[str, Any]] | None = None


def _pulse(data: Blocks, line: int) -> int:
    base = HR_PULSE_VALUE + 2 * (line - 1)
    return (data.holding[base] << 16) | data.holding[base + 1]


SENSORS: tuple[NeptunSensorDescription, ...] = (
    NeptunSensorDescription(
        key="ups_charge",
        translation_key="ups_charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        block="input",
        value_fn=lambda d: d.input[IR_UPS_PERCENT],
    ),
    NeptunSensorDescription(
        key="errors",
        translation_key="errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        block="input",
        value_fn=lambda d: d.input[IR_ERRORS],
        attrs_fn=lambda d: {"errors": decode_errors(d.input[IR_ERRORS])},
    ),
    NeptunSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        block="input",
        value_fn=lambda d: decode_firmware(d.input[IR_FW_VERSION]),
    ),
    NeptunSensorDescription(
        key="hardware",
        translation_key="hardware",
        entity_category=EntityCategory.DIAGNOSTIC,
        block="input",
        value_fn=lambda d: d.input[IR_HW_VERSION],
    ),
)


class NeptunSensor(NeptunEntity, SensorEntity):
    entity_description: NeptunSensorDescription

    def __init__(
        self, coordinator: NeptunCoordinator, description: NeptunSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._block = description.block

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None


class NeptunWiredDiffSensor(NeptunWiredEntity, SensorEntity):
    _attr_translation_key = "wired_diff"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, line, "wired_diff")

    @property
    def native_value(self) -> int:
        return to_signed16(self.coordinator.data.holding[HR_WIRED_DIFF + self._line - 1])


class NeptunPulseCounterSensor(NeptunWiredEntity, SensorEntity):
    _attr_translation_key = "pulse_counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, line, "pulse_counter")

    @property
    def native_value(self) -> int:
        return _pulse(self.coordinator.data, self._line)


class NeptunValveLineSensor(NeptunEntity, SensorEntity):
    """State of a valve line reported with feedback enabled."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = VALVE_STATES
    _attr_translation_key = "valve_line"
    _block = "input"

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, f"valve_line_{line}")
        self._line = line
        self._attr_translation_placeholders = {"line": str(line)}

    @property
    def native_value(self) -> str:
        return decode_valve_line(self.coordinator.data.input[IR_VALVE_LINES], self._line)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        raw = self.coordinator.data.input[IR_VALVE_LINES] >> (8 * (self._line - 1)) & 0xFF
        return {"raw": raw}


class NeptunLinkSensor(NeptunLinkEntity, SensorEntity):
    """Link health counters, always available."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: NeptunCoordinator,
        key: str,
        value_fn: Callable[[NeptunCoordinator], Any],
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._value_fn = value_fn
        self._attr_device_class = device_class
        if device_class is None:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | datetime | None:
        return self._value_fn(self.coordinator)


class NeptunRadioBattery(NeptunRadioEntity, SensorEntity):
    _attr_translation_key = "radio_battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        super().__init__(coordinator, index, "battery")

    @property
    def native_value(self) -> int | None:
        radio = self.coordinator.radio(self._index)
        return radio.battery_percent if radio else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        radio = self.coordinator.radio(self._index)
        return {"level": radio.battery_level} if radio else {}


class NeptunRadioRssi(NeptunRadioEntity, SensorEntity):
    _attr_translation_key = "radio_rssi"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        super().__init__(coordinator, index, "rssi")

    @property
    def native_value(self) -> int | None:
        radio = self.coordinator.radio(self._index)
        return radio.rssi if radio else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    lines = entry.options.get(CONF_VALVE_LINES, DEFAULT_VALVE_LINES)
    async_add_entities(
        [
            *(NeptunSensor(coordinator, d) for d in SENSORS),
            *(NeptunValveLineSensor(coordinator, n) for n in range(1, lines + 1)),
            NeptunLinkSensor(
                coordinator,
                "last_success",
                lambda c: c.last_success,
                SensorDeviceClass.TIMESTAMP,
            ),
            NeptunLinkSensor(coordinator, "failures", lambda c: c.consecutive_failures),
            NeptunLinkSensor(coordinator, "timeouts", lambda c: c.client.stats.timeouts),
            NeptunLinkSensor(coordinator, "exceptions", lambda c: c.client.stats.exceptions),
        ]
    )
    async_add_radio_entities(
        entry,
        async_add_entities,
        lambda c, i: (NeptunRadioBattery(c, i), NeptunRadioRssi(c, i)),
    )
    async_add_wired_entities(
        entry,
        async_add_entities,
        lambda c, n: (NeptunWiredDiffSensor(c, n), NeptunPulseCounterSensor(c, n)),
    )
