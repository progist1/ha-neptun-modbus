"""Base entities."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    NeptunConfigEntry,
    NeptunCoordinator,
    main_identifier,
    radio_identifier,
    wired_identifier,
)
from .registers import IR_FW_VERSION, RADIO_FIRST_NUMBER, decode_firmware


def main_device_info(coordinator: NeptunCoordinator) -> DeviceInfo:
    sw = None
    data = coordinator.data
    if data is not None and data.input is not None:
        sw = decode_firmware(data.input[IR_FW_VERSION])
    return DeviceInfo(
        identifiers={main_identifier(coordinator.config_entry)},
        name="Neptun",
        manufacturer="Neptun",
        model="Valve control module (Modbus RTU)",
        sw_version=sw,
    )


def async_register_main_device(hass: HomeAssistant, coordinator: NeptunCoordinator) -> None:
    """Create the main device up front so child devices can reference it by id."""
    info = main_device_info(coordinator)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=coordinator.config_entry.entry_id,
        identifiers=info["identifiers"],
        name=info["name"],
        manufacturer=info["manufacturer"],
        model=info["model"],
        sw_version=info["sw_version"],
    )


def main_device_id(coordinator: NeptunCoordinator) -> str | None:
    device = dr.async_get(coordinator.hass).async_get_device_by_identifier(
        main_identifier(coordinator.config_entry), coordinator.config_entry.entry_id
    )
    return device.id if device else None


class NeptunEntity(CoordinatorEntity[NeptunCoordinator]):
    """Entity of the main Neptun device, available while its register block is readable."""

    _attr_has_entity_name = True
    # name of the register block this entity depends on; None = needs only the link
    _block: str | None = "holding"

    def __init__(self, coordinator: NeptunCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = self._build_device_info()

    def _build_device_info(self) -> DeviceInfo:
        return main_device_info(self.coordinator)

    @property
    def available(self) -> bool:
        if self._block is None:
            return self.coordinator.link_ok
        return self.coordinator.block_ok(self._block)


class NeptunLinkEntity(NeptunEntity):
    """Entity that describes the link itself, so it is always available."""

    @property
    def available(self) -> bool:
        return True


class NeptunRadioEntity(NeptunEntity):
    """Entity of a radio sensor child device."""

    _block = "holding"

    def __init__(self, coordinator: NeptunCoordinator, index: int, key: str) -> None:
        self._index = index
        self._number = RADIO_FIRST_NUMBER + index
        super().__init__(coordinator, f"radio_{self._number}_{key}")

    def _build_device_info(self) -> DeviceInfo:
        coordinator = self.coordinator
        return DeviceInfo(
            identifiers={radio_identifier(coordinator.config_entry, self._index)},
            name=f"Neptun radio sensor {self._number}",
            manufacturer="Neptun",
            model="Radio leak sensor",
            via_device_id=main_device_id(coordinator),
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.radio(self._index) is not None


class NeptunWiredEntity(NeptunEntity):
    """Entity of a wired input line child device; exists while the line mode is not "unused"."""

    _block = "holding"

    def __init__(self, coordinator: NeptunCoordinator, line: int, key: str) -> None:
        self._line = line
        super().__init__(coordinator, f"{key}_{line}")

    def _build_device_info(self) -> DeviceInfo:
        coordinator = self.coordinator
        return DeviceInfo(
            identifiers={wired_identifier(coordinator.config_entry, self._line)},
            name=f"Neptun wired line {self._line}",
            manufacturer="Neptun",
            model="Wired input line",
            via_device_id=main_device_id(coordinator),
        )

    @property
    def available(self) -> bool:
        return super().available and self._line in self.coordinator.wired_lines


def async_add_wired_entities(
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[NeptunCoordinator, int], Iterable[Entity]],
) -> None:
    """Create wired line entities now and whenever a line is (re)enabled."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _discover() -> None:
        known.intersection_update(coordinator.wired_lines)
        new = coordinator.wired_lines - known
        if not new:
            return
        known.update(new)
        async_add_entities([e for n in sorted(new) for e in factory(coordinator, n)])

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


def async_add_radio_entities(
    entry: NeptunConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[NeptunCoordinator, int], Iterable[Entity]],
) -> None:
    """Create radio sensor entities now and whenever a new sensor is discovered."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _discover() -> None:
        known.intersection_update(coordinator.radio_indexes)
        new = coordinator.radio_indexes - known
        if not new:
            return
        known.update(new)
        async_add_entities([e for i in sorted(new) for e in factory(coordinator, i)])

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))
