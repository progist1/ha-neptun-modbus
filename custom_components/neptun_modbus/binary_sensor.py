"""Binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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
    COIL_LEAK,
    COIL_SIREN,
    DI_ON_UPS,
    DI_UPS_PRESENT,
    DI_VALVES_POWER,
    ERROR_BITS,
    HR_WIRED_CONFIG,
    IR_ERRORS,
    IR_WIRED_STATE,
    WIRED_MODE_MASK,
    Blocks,
    WiredMode,
    decode_errors,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NeptunBinarySensorDescription(BinarySensorEntityDescription):
    block: str
    value_fn: Callable[[Blocks], bool]


DESCRIPTIONS: tuple[NeptunBinarySensorDescription, ...] = (
    NeptunBinarySensorDescription(
        key="leak",
        translation_key="leak",
        device_class=BinarySensorDeviceClass.MOISTURE,
        block="coils",
        value_fn=lambda d: d.coils[COIL_LEAK],
    ),
    NeptunBinarySensorDescription(
        key="siren_active",
        translation_key="siren_active",
        block="coils",
        value_fn=lambda d: d.coils[COIL_SIREN],
    ),
    NeptunBinarySensorDescription(
        key="valves_power",
        translation_key="valves_power",
        device_class=BinarySensorDeviceClass.POWER,
        block="discrete",
        value_fn=lambda d: d.discrete[DI_VALVES_POWER],
    ),
    NeptunBinarySensorDescription(
        key="ups_present",
        translation_key="ups_present",
        entity_category=EntityCategory.DIAGNOSTIC,
        block="discrete",
        value_fn=lambda d: d.discrete[DI_UPS_PRESENT],
    ),
    NeptunBinarySensorDescription(
        key="on_ups",
        translation_key="on_ups",
        block="discrete",
        value_fn=lambda d: d.discrete[DI_ON_UPS],
    ),
    *(
        NeptunBinarySensorDescription(
            key=f"error_{key}",
            translation_key=f"error_{key}",
            device_class=BinarySensorDeviceClass.PROBLEM,
            entity_category=EntityCategory.DIAGNOSTIC,
            block="input",
            value_fn=lambda d, bit=bit: bool(d.input[IR_ERRORS] & (1 << bit)),
        )
        for bit, (key, _) in ERROR_BITS.items()
    ),
)


class NeptunBinarySensor(NeptunEntity, BinarySensorEntity):
    entity_description: NeptunBinarySensorDescription

    def __init__(
        self, coordinator: NeptunCoordinator, description: NeptunBinarySensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._block = description.block

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator.data)


class NeptunProblemSensor(NeptunEntity, BinarySensorEntity):
    """Aggregate of all error bits, with readable descriptions in the attributes."""

    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _block = "input"

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.input[IR_ERRORS] != 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"errors": decode_errors(self.coordinator.data.input[IR_ERRORS])}


class NeptunConnectionSensor(NeptunLinkEntity, BinarySensorEntity):
    """Link to the module; stays available to report its own loss."""

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def is_on(self) -> bool:
        return self.coordinator.link_ok


class NeptunWiredLineSensor(NeptunWiredEntity, BinarySensorEntity):
    """State of a wired input line; meaning depends on the configured line mode."""

    _attr_translation_key = "wired_line"
    _block = "input"

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, line, "wired_line")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.block_ok("holding")

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        raw = self.coordinator.data.holding[HR_WIRED_CONFIG + self._line - 1]
        if raw & WIRED_MODE_MASK == WiredMode.SENSOR:
            return BinarySensorDeviceClass.MOISTURE
        return None

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.input[IR_WIRED_STATE] & (1 << (self._line - 1)))


class NeptunRadioLeak(NeptunRadioEntity, BinarySensorEntity):
    _attr_translation_key = "radio_leak"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        super().__init__(coordinator, index, "leak")

    @property
    def is_on(self) -> bool:
        radio = self.coordinator.radio(self._index)
        return bool(radio and radio.leak)


class NeptunRadioLost(NeptunRadioEntity, BinarySensorEntity):
    _attr_translation_key = "radio_lost"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        super().__init__(coordinator, index, "lost")

    @property
    def is_on(self) -> bool:
        radio = self.coordinator.radio(self._index)
        return bool(radio and radio.lost)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(NeptunBinarySensor(coordinator, d) for d in DESCRIPTIONS),
            NeptunProblemSensor(coordinator),
            NeptunConnectionSensor(coordinator),
        ]
    )
    async_add_radio_entities(
        entry,
        async_add_entities,
        lambda c, i: (NeptunRadioLeak(c, i), NeptunRadioLost(c, i)),
    )
    async_add_wired_entities(entry, async_add_entities, lambda c, n: (NeptunWiredLineSensor(c, n),))
