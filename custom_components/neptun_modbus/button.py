"""Buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import (
    NeptunEntity,
    NeptunRadioEntity,
    NeptunWiredEntity,
    async_add_radio_entities,
    async_add_wired_entities,
)
from .registers import (
    COIL_LEAK,
    COIL_SIREN,
    HR_RADIO_FIRST,
    HR_RESET,
    HR_WIRED_DIFF,
    ResetCommand,
)

PARALLEL_UPDATES = 1


class NeptunButton(NeptunEntity, ButtonEntity):
    """Button with a fixed write action."""

    def __init__(
        self,
        coordinator: NeptunCoordinator,
        key: str,
        block: str,
        *,
        category: EntityCategory | None = None,
        enabled_default: bool = True,
        device_class: ButtonDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._block = block
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = enabled_default
        self._attr_device_class = device_class


class NeptunResetLeak(NeptunButton):
    """Clear the leak status and silence the siren."""

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "reset_leak", "coils")

    async def async_press(self) -> None:
        await self.coordinator.async_write_coil(COIL_LEAK, False)


class NeptunMuteSiren(NeptunButton):
    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "mute_siren", "coils")

    async def async_press(self) -> None:
        await self.coordinator.async_write_coil(COIL_SIREN, False)


class NeptunSaveWiredCount(NeptunWiredEntity, ButtonEntity):
    """Store the current number of sensors on the line as the reference."""

    _attr_translation_key = "save_wired_count"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: NeptunCoordinator, line: int) -> None:
        super().__init__(coordinator, line, "save_wired_count")

    async def async_press(self) -> None:
        await self.coordinator.async_write_register(HR_WIRED_DIFF + self._line - 1, 0)


class NeptunReboot(NeptunButton):
    """Reboot the module; hidden until the user enables it."""

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(
            coordinator,
            "reboot",
            "holding",
            category=EntityCategory.CONFIG,
            enabled_default=False,
            device_class=ButtonDeviceClass.RESTART,
        )

    async def async_press(self) -> None:
        await self.coordinator.async_write_register(HR_RESET, int(ResetCommand.REBOOT))


class NeptunForgetRadio(NeptunRadioEntity, ButtonEntity):
    """Remove the radio sensor from the module; hidden until the user enables it."""

    _attr_translation_key = "forget_radio"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: NeptunCoordinator, index: int) -> None:
        super().__init__(coordinator, index, "forget")

    async def async_press(self) -> None:
        await self.coordinator.async_write_register(HR_RADIO_FIRST + self._index, 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            NeptunResetLeak(coordinator),
            NeptunMuteSiren(coordinator),
            NeptunReboot(coordinator),
        ]
    )
    async_add_radio_entities(entry, async_add_entities, lambda c, i: (NeptunForgetRadio(c, i),))
    async_add_wired_entities(entry, async_add_entities, lambda c, n: (NeptunSaveWiredCount(c, n),))
