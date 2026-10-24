"""Numbers."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import NeptunEntity, NeptunWiredEntity, async_add_wired_entities
from .registers import (
    BRIGHTNESS_MAX,
    HR_BRIGHTNESS,
    HR_FLOOR_WASH_LEFT,
    HR_PULSE_VALUE,
    HR_SIREN_MINUTES,
    HR_VALVE_POWER_TIMEOUT,
    SIREN_ALWAYS,
    VALVE_POWER_TIMEOUT_MAX,
    VALVE_POWER_TIMEOUT_MIN,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NeptunNumberDescription(NumberEntityDescription):
    register: int


NUMBERS = (
    NeptunNumberDescription(
        key="siren_minutes",
        translation_key="siren_minutes",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=SIREN_ALWAYS,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        mode=NumberMode.BOX,
        register=HR_SIREN_MINUTES,
    ),
    NeptunNumberDescription(
        key="valve_power_timeout",
        translation_key="valve_power_timeout",
        entity_category=EntityCategory.CONFIG,
        native_min_value=VALVE_POWER_TIMEOUT_MIN,
        native_max_value=VALVE_POWER_TIMEOUT_MAX,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=NumberDeviceClass.DURATION,
        mode=NumberMode.BOX,
        register=HR_VALVE_POWER_TIMEOUT,
    ),
    NeptunNumberDescription(
        key="brightness",
        translation_key="brightness",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=BRIGHTNESS_MAX,
        native_step=1,
        mode=NumberMode.SLIDER,
        register=HR_BRIGHTNESS,
    ),
    NeptunNumberDescription(
        key="floor_wash_left",
        translation_key="floor_wash_left",
        native_min_value=0,
        native_max_value=240,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        mode=NumberMode.BOX,
        register=HR_FLOOR_WASH_LEFT,
    ),
)


class NeptunNumber(NeptunEntity, NumberEntity):
    entity_description: NeptunNumberDescription

    def __init__(
        self, coordinator: NeptunCoordinator, description: NeptunNumberDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return self.coordinator.data.holding[self.entity_description.register]

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_register(self.entity_description.register, int(value))


class NeptunPulseCounterNumber(NeptunWiredEntity, NumberEntity):
    """32-bit pulse counter value (hi word first)."""

    _attr_translation_key = "pulse_counter_value"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_native_min_value = 0
    _attr_native_max_value = 0xFFFFFFFF
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, line, "pulse_counter_value")
        self._base = HR_PULSE_VALUE + 2 * (line - 1)

    @property
    def native_value(self) -> float:
        hr = self.coordinator.data.holding
        return (hr[self._base] << 16) | hr[self._base + 1]

    async def async_set_native_value(self, value: float) -> None:
        raw = int(value)
        await self.coordinator.async_write_registers(self._base, [raw >> 16, raw & 0xFFFF])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(NeptunNumber(coordinator, d) for d in NUMBERS),
        ]
    )
    async_add_wired_entities(
        entry, async_add_entities, lambda c, n: (NeptunPulseCounterNumber(c, n),)
    )
