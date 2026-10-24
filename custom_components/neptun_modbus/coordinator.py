"""Data update coordinator: polls the register blocks and tracks link health."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import NeptunClient, NeptunConnectionError, NeptunError, NeptunTimeoutError
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAIL_THRESHOLD,
    ISSUE_AFTER,
    ISSUE_NO_CONNECTION,
    RADIO_REMOVE_AFTER,
)
from .registers import (
    COIL_COUNT,
    DI_COUNT,
    HR_COUNT,
    HR_RADIO_FIRST,
    HR_WIRED_CONFIG,
    IR_COUNT,
    RADIO_COUNT,
    WIRED_LINES,
    WIRED_MODE_MASK,
    Blocks,
    RadioSensor,
    WiredMode,
    decode_radio,
)

_LOGGER = logging.getLogger(__name__)

type NeptunConfigEntry = ConfigEntry[NeptunCoordinator]

BLOCKS = ("coils", "discrete", "holding", "input")


class NeptunCoordinator(DataUpdateCoordinator[Blocks]):
    """Owns the client and the latest register image."""

    config_entry: NeptunConfigEntry

    def __init__(self, hass: HomeAssistant, entry: NeptunConfigEntry, client: NeptunClient) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.consecutive_failures = 0
        self.last_success: object | None = None
        self.last_error: str | None = None
        self.block_errors: dict[str, str | None] = {}
        self._down_since: float | None = None
        self._radio_missing: dict[int, int] = {}
        self.radio_indexes: set[int] = set()
        self.wired_lines: set[int] = set()

    # --- state helpers used by entities ---
    @property
    def link_ok(self) -> bool:
        return self.last_update_success and self.consecutive_failures < FAIL_THRESHOLD

    @property
    def link_state(self) -> str:
        """connected: all blocks read, degraded: some do not answer, disconnected: none."""
        if not self.link_ok:
            return "disconnected"
        if self.data is not None and not all(self.data.ok.values()):
            return "degraded"
        return "connected"

    def block_ok(self, block: str) -> bool:
        return self.link_ok and self.data is not None and self.data.ok.get(block, False)

    def radio(self, index: int) -> RadioSensor | None:
        if self.data is None or self.data.holding is None:
            return None
        return decode_radio(index, self.data.holding[HR_RADIO_FIRST + index])

    # --- polling ---
    async def _async_update_data(self) -> Blocks:
        readers = {
            "coils": lambda: self.client.read_coils(0, COIL_COUNT),
            "discrete": lambda: self.client.read_discrete_inputs(0, DI_COUNT),
            "holding": lambda: self.client.read_holding_registers(0, HR_COUNT),
            "input": lambda: self.client.read_input_registers(0, IR_COUNT),
        }
        previous = self.data
        new = Blocks()
        any_ok = False
        dead_reason: str | None = None
        for name, reader in readers.items():
            if dead_reason is not None:
                # the first block got no answer at all: the module is gone, do not burn the cycle
                error: str | None = dead_reason
            else:
                try:
                    setattr(new, name, await reader())
                    new.ok[name] = True
                    self.block_errors[name] = None
                    any_ok = True
                    continue
                except (NeptunTimeoutError, NeptunConnectionError) as err:
                    error = str(err)
                    if not any_ok:
                        dead_reason = error
                except NeptunError as err:
                    error = str(err)
                _LOGGER.debug("block %s failed: %s", name, error)
            new.ok[name] = False
            self.block_errors[name] = error
            self.last_error = error
            if previous is not None:
                setattr(new, name, getattr(previous, name))

        if not any(new.ok.values()):
            self.consecutive_failures += 1
            self._mark_down()
            if previous is None or self.consecutive_failures >= FAIL_THRESHOLD:
                raise UpdateFailed(self.last_error or "no answer from module")
            # transient glitch: keep the previous image and its availability
            return previous

        self.consecutive_failures = 0
        self.last_success = dt_util.utcnow()
        if all(new.ok.values()):
            self.last_error = None
        self._mark_up()
        if new.ok["holding"]:
            self._track_radios(new)
            self._track_wired(new)
        return new

    def _mark_down(self) -> None:
        if self._down_since is None:
            self._down_since = time.monotonic()
        if time.monotonic() - self._down_since >= ISSUE_AFTER and self.config_entry is not None:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{ISSUE_NO_CONNECTION}_{self.config_entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_NO_CONNECTION,
                translation_placeholders={"error": self.last_error or ""},
            )

    def _mark_up(self) -> None:
        self._down_since = None
        ir.async_delete_issue(
            self.hass, DOMAIN, f"{ISSUE_NO_CONNECTION}_{self.config_entry.entry_id}"
        )

    def _track_radios(self, data: Blocks) -> None:
        assert data.holding is not None
        present = {
            i
            for i in range(RADIO_COUNT)
            if decode_radio(i, data.holding[HR_RADIO_FIRST + i]) is not None
        }
        for i in present:
            self.radio_indexes.add(i)
            self._radio_missing.pop(i, None)
        for i in self.radio_indexes - present:
            self._radio_missing[i] = self._radio_missing.get(i, 0) + 1
            if self._radio_missing[i] >= RADIO_REMOVE_AFTER:
                self.radio_indexes.discard(i)
                del self._radio_missing[i]
                _LOGGER.info("radio sensor %d is gone, removing device", i + 11)
                self._remove_device(radio_identifier(self.config_entry, i))

    def _track_wired(self, data: Blocks) -> None:
        """A wired line has a device while its mode is not "unused" (settable from HA)."""
        assert data.holding is not None
        active = {
            n
            for n in range(1, WIRED_LINES + 1)
            if data.holding[HR_WIRED_CONFIG + n - 1] & WIRED_MODE_MASK != WiredMode.UNUSED
        }
        raw = [data.holding[HR_WIRED_CONFIG + n] for n in range(WIRED_LINES)]
        if active != self.wired_lines:
            _LOGGER.debug(
                "wired line config HR4..6=%s active lines %s -> %s",
                raw,
                sorted(self.wired_lines),
                sorted(active),
            )
        for n in self.wired_lines - active:
            _LOGGER.info("wired line %d is not used, removing device", n)
            self._remove_device(wired_identifier(self.config_entry, n))
        self.wired_lines = active

    def _remove_device(self, identifier: tuple[str, str]) -> None:
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(identifier, self.config_entry.entry_id)
        if device is not None:
            registry.async_update_device(
                device.id, remove_config_entry_id=self.config_entry.entry_id
            )

    # --- writes: every write is followed by a refresh so the UI shows what the module accepted ---
    async def async_write_coil(self, address: int, value: bool) -> None:
        await self._write(self.client.write_coil(address, value))

    async def async_write_register(self, address: int, value: int) -> None:
        await self._write(self.client.write_register(address, value))

    async def async_write_registers(self, address: int, values: list[int]) -> None:
        await self._write(self.client.write_registers(address, values))

    async def _write(self, coro) -> None:  # noqa: ANN001
        try:
            await coro
        except NeptunError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.async_refresh()


def radio_identifier(entry: ConfigEntry, index: int) -> tuple[str, str]:
    return (DOMAIN, f"{entry.entry_id}_radio_{index + 11}")


def wired_identifier(entry: ConfigEntry, line: int) -> tuple[str, str]:
    return (DOMAIN, f"{entry.entry_id}_wired_{line}")


def main_identifier(entry: ConfigEntry) -> tuple[str, str]:
    return (DOMAIN, entry.entry_id)
