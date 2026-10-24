"""Selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import NeptunEntity, NeptunWiredEntity, async_add_wired_entities
from .registers import (
    HR_MODE,
    HR_PULSE_STEP,
    HR_RELAY_MODE,
    HR_WIRED_CONFIG,
    WIRED_FEEDBACK,
    WIRED_LINES,
    WIRED_MODE_MASK,
    OperatingMode,
    RelayMode,
    WiredMode,
)

PARALLEL_UPDATES = 1

PULSE_STEPS = ["1", "10", "100"]


class NeptunEnumSelect(NeptunEntity, SelectEntity):
    """Select over an IntEnum stored in one holding register."""

    def __init__(
        self,
        coordinator: NeptunCoordinator,
        key: str,
        register: int,
        enum_cls: type,
        category: EntityCategory | None = EntityCategory.CONFIG,
    ) -> None:
        super().__init__(coordinator, key)
        self._register = register
        self._enum = enum_cls
        self._attr_translation_key = key
        self._attr_entity_category = category
        self._attr_options = [m.name.lower() for m in enum_cls]

    @property
    def current_option(self) -> str | None:
        try:
            return self._enum(self.coordinator.data.holding[self._register]).name.lower()
        except ValueError:
            return None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write_register(self._register, int(self._enum[option.upper()]))


class NeptunWiredModeSelect(NeptunEntity, SelectEntity):
    """Line mode in bits 6..0 of the line config; bit 7 (feedback) only exists in sensor mode."""

    _attr_translation_key = "wired_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [m.name.lower() for m in WiredMode]
    _block = "holding"

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, f"wired_mode_{line}")
        self._register = HR_WIRED_CONFIG + line - 1
        self._attr_translation_placeholders = {"line": str(line)}

    @property
    def current_option(self) -> str | None:
        try:
            raw = self.coordinator.data.holding[self._register]
            return WiredMode(raw & WIRED_MODE_MASK).name.lower()
        except ValueError:
            return None

    async def async_select_option(self, option: str) -> None:
        mode = WiredMode[option.upper()]
        feedback = self.coordinator.data.holding[self._register] & WIRED_FEEDBACK
        value = int(mode) | (feedback if mode == WiredMode.SENSOR else 0)
        await self.coordinator.async_write_register(self._register, value)


class NeptunPulseStepSelect(NeptunWiredEntity, SelectEntity):
    _attr_translation_key = "pulse_step"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_options = PULSE_STEPS

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, line, "pulse_step")
        self._register = HR_PULSE_STEP + line - 1

    @property
    def current_option(self) -> str | None:
        value = str(self.coordinator.data.holding[self._register])
        return value if value in PULSE_STEPS else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write_register(self._register, int(option))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            NeptunEnumSelect(coordinator, "relay_mode", HR_RELAY_MODE, RelayMode),
            NeptunEnumSelect(coordinator, "operating_mode", HR_MODE, OperatingMode, category=None),
            *(NeptunWiredModeSelect(coordinator, n) for n in range(1, WIRED_LINES + 1)),
        ]
    )
    async_add_wired_entities(entry, async_add_entities, lambda c, n: (NeptunPulseStepSelect(c, n),))
