"""Async Modbus RTU client: one owner of the serial port, serialized requests, retries."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException

_LOGGER = logging.getLogger(__name__)

RETRY_PAUSE = 0.2


class NeptunError(Exception):
    """Base error of the client."""


class NeptunConnectionError(NeptunError):
    """The serial port cannot be opened or was lost."""


class NeptunTimeoutError(NeptunError):
    """No valid answer (timeout, bad CRC) after all retries."""


class NeptunProtocolError(NeptunError):
    """The module answered with a Modbus exception response."""


@dataclass(slots=True)
class ClientStats:
    requests: int = 0
    timeouts: int = 0
    exceptions: int = 0
    reconnects: int = 0


class NeptunClient:
    """Serialized access to the module. All public coroutines raise NeptunError subclasses."""

    def __init__(
        self,
        port: str,
        slave: int,
        baudrate: int,
        timeout: float = 1.5,
        retries: int = 3,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._port = port
        self._slave = slave
        self._retries = max(1, int(retries))
        factory = client_factory or AsyncModbusSerialClient
        # pymodbus own retries are disabled, we retry (and count) ourselves
        self._client = factory(
            port,
            baudrate=baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=timeout,
            retries=0,
        )
        self._lock = asyncio.Lock()
        self.stats = ClientStats()

    @property
    def connected(self) -> bool:
        return bool(self._client.connected)

    async def connect(self) -> None:
        try:
            await self._client.connect()
        except (OSError, ModbusException) as err:
            raise NeptunConnectionError(f"cannot open {self._port}: {err}") from err
        if not self._client.connected:
            raise NeptunConnectionError(f"cannot open {self._port}")

    async def close(self) -> None:
        self._client.close()

    async def read_coils(self, address: int, count: int) -> list[bool]:
        rr = await self._call(self._client.read_coils, address, count=count)
        return [bool(b) for b in rr.bits[:count]]

    async def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        rr = await self._call(self._client.read_discrete_inputs, address, count=count)
        return [bool(b) for b in rr.bits[:count]]

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        rr = await self._call(self._client.read_holding_registers, address, count=count)
        return list(rr.registers[:count])

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        rr = await self._call(self._client.read_input_registers, address, count=count)
        return list(rr.registers[:count])

    async def write_coil(self, address: int, value: bool) -> None:
        await self._call(self._client.write_coil, address, value)

    async def write_register(self, address: int, value: int) -> None:
        await self._call(self._client.write_register, address, value)

    async def write_registers(self, address: int, values: list[int]) -> None:
        await self._call(self._client.write_registers, address, values)

    async def _call(self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            return await self._call_locked(func, *args, **kwargs)

    async def _call_locked(
        self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        last: Exception | None = None
        for attempt in range(1, self._retries + 1):
            if not self._client.connected:
                self.stats.reconnects += 1
                await self.connect()
            self.stats.requests += 1
            try:
                result = await func(*args, device_id=self._slave, **kwargs)
            except ConnectionException as err:
                self._client.close()
                raise NeptunConnectionError(f"serial port lost: {err}") from err
            except ModbusIOException as err:
                self.stats.timeouts += 1
                last = err
                _LOGGER.debug("attempt %d/%d failed: %s", attempt, self._retries, err)
                await asyncio.sleep(RETRY_PAUSE * attempt)
                continue
            except (TimeoutError, ModbusException) as err:
                self.stats.timeouts += 1
                last = err
                await asyncio.sleep(RETRY_PAUSE * attempt)
                continue
            except OSError as err:
                self._client.close()
                raise NeptunConnectionError(f"serial error: {err}") from err
            _LOGGER.debug(
                "%s%s %s -> %s",
                func.__name__,
                args,
                kwargs or "",
                getattr(result, "registers", None) or getattr(result, "bits", None) or "ok",
            )
            if result.isError():
                # an exception response is a valid answer: do not retry
                self.stats.exceptions += 1
                raise NeptunProtocolError(f"module returned {result}")
            return result
        raise NeptunTimeoutError(f"no valid answer after {self._retries} attempts: {last}")
