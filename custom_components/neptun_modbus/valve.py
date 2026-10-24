"""Valves."""

from __future__ import annotations

from homeassistant.components.valve import ValveDeviceClass, ValveEntity, ValveEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NeptunConfigEntry, NeptunCoordinator
from .entity import NeptunEntity
from .registers import COIL_VALVES

PARALLEL_UPDATES = 1


class NeptunValves(NeptunEntity, ValveEntity):
    """All water valves behind the module (coil 1: 1 = open, 0 = closed or closing)."""

    _attr_translation_key = "valves"
    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _block = "coils"

    def __init__(self, coordinator: NeptunCoordinator) -> None:
        super().__init__(coordinator, "valves")

    @property
    def is_closed(self) -> bool:
        return not self.coordinator.data.coils[COIL_VALVES]

    async def async_open_valve(self) -> None:
        await self.coordinator.async_write_coil(COIL_VALVES, True)

    async def async_close_valve(self) -> None:
        await self.coordinator.async_write_coil(COIL_VALVES, False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NeptunValves(entry.runtime_data)])
