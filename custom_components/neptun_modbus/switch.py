"""Switches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import NeptunEntity, NeptunWiredEntity, async_add_wired_entities
from .registers import (
    COIL_BUTTON_LED,
    COIL_CHILD_LOCK,
    COIL_CLOSE_ON_LOW_UPS,
    COIL_CLOSE_ON_SENSOR_LOSS,
    COIL_RELAY,
    COIL_VALVE_FEEDBACK,
    HR_RELAY_MODE,
    HR_WIRED_CONFIG,
    WIRED_FEEDBACK,
    WIRED_MODE_MASK,
    RelayMode,
    WiredMode,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NeptunSwitchDescription(SwitchEntityDescription):
    coil: int


COIL_SWITCHES = (
    NeptunSwitchDescription(
        key="valve_feedback",
        translation_key="valve_feedback",
        entity_category=EntityCategory.CONFIG,
        coil=COIL_VALVE_FEEDBACK,
    ),
    NeptunSwitchDescription(
        key="close_on_low_ups",
        translation_key="close_on_low_ups",
        entity_category=EntityCategory.CONFIG,
        coil=COIL_CLOSE_ON_LOW_UPS,
    ),
    NeptunSwitchDescription(
        key="close_on_sensor_loss",
        translation_key="close_on_sensor_loss",
        entity_category=EntityCategory.CONFIG,
        coil=COIL_CLOSE_ON_SENSOR_LOSS,
    ),
    NeptunSwitchDescription(
        key="child_lock",
        translation_key="child_lock",
        entity_category=EntityCategory.CONFIG,
        coil=COIL_CHILD_LOCK,
    ),
    NeptunSwitchDescription(
        key="button_led",
        translation_key="button_led",
        entity_category=EntityCategory.CONFIG,
        coil=COIL_BUTTON_LED,
    ),
)


class NeptunCoilSwitch(NeptunEntity, SwitchEntity):
    entity_description: NeptunSwitchDescription
    _block = "coils"

    def __init__(
        self, coordinator: NeptunCoordinator, description: NeptunSwitchDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.coils[self.entity_description.coil]

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_coil(self.entity_description.coil, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_coil(self.entity_description.coil, False)


class NeptunRelaySwitch(NeptunCoilSwitch):
    """The relay can be switched by hand only in relay mode MANUAL; otherwise it just reports."""

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(
            coordinator,
            NeptunSwitchDescription(key="relay", translation_key="relay", coil=COIL_RELAY),
        )

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and self.coordinator.block_ok("holding")
            and data.holding[HR_RELAY_MODE] == RelayMode.MANUAL
        )


class NeptunWiredFeedbackSwitch(NeptunWiredEntity, SwitchEntity):
    """Bit 7 of the line config; the module only allows it in sensor mode."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "wired_feedback"

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, line, "wired_feedback")

    @property
    def _raw(self) -> int:
        return self.coordinator.data.holding[HR_WIRED_CONFIG + self._line - 1]

    @property
    def available(self) -> bool:
        return super().available and self._raw & WIRED_MODE_MASK == WiredMode.SENSOR

    @property
    def is_on(self) -> bool:
        return bool(self._raw & WIRED_FEEDBACK)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_register(
            HR_WIRED_CONFIG + self._line - 1, self._raw | WIRED_FEEDBACK
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write_register(
            HR_WIRED_CONFIG + self._line - 1, self._raw & ~WIRED_FEEDBACK
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(NeptunCoilSwitch(coordinator, d) for d in COIL_SWITCHES),
            NeptunRelaySwitch(coordinator),
        ]
    )
    async_add_wired_entities(
        entry, async_add_entities, lambda c, n: (NeptunWiredFeedbackSwitch(c, n),)
    )
