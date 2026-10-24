"""In-memory simulator of the Neptun module with the write semantics from the vendor PDF."""

from __future__ import annotations

import json
from pathlib import Path

from pymodbus.exceptions import ConnectionException, ModbusIOException

SNAPSHOT = Path(__file__).parent / "fixtures" / "snapshot_2026-10-24.json"


class Response:
    def __init__(self, *, bits=None, registers=None, error: str | None = None) -> None:
        self.bits = bits or []
        self.registers = registers or []
        self._error = error

    def isError(self) -> bool:  # noqa: N802 - pymodbus API
        return self._error is not None

    def __str__(self) -> str:
        return self._error or "ok"


class FakeModule:
    """Register image + fault injection. Every write is silently ignored when the PDF says so."""

    def __init__(self) -> None:
        snap = json.loads(SNAPSHOT.read_text())
        self.coils: list[bool] = [bool(v) for v in snap["coils"]]
        self.discrete: list[bool] = [bool(v) for v in snap["discrete_inputs"]]
        self.input: list[int] = list(snap["input_registers"])
        self.holding: list[int] = list(snap["holding_registers"])
        self.last_reset_command: int | None = None
        # fault injection
        self.disconnected = False  # port gone
        self.silent = False  # every request times out
        self.silent_functions: set[str] = set()  # e.g. {"read_holding_registers"}
        self.exception_functions: set[str] = set()
        self.fail_next = 0  # next N requests time out, then the module recovers
        self.log: list[tuple[str, int, object]] = []

    # --- fault gate used by the client ---
    def gate(self, function: str) -> Response | None:
        if self.disconnected:
            raise ConnectionException("port lost")
        if self.silent or function in self.silent_functions:
            raise ModbusIOException("No response received")
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ModbusIOException("No response received")
        if function in self.exception_functions:
            return Response(error="ExceptionResponse(illegal address)")
        return None

    # --- write semantics ---
    def write_coil(self, address: int, value: bool) -> Response:
        self.log.append(("coil", address, value))
        if not 0 <= address < len(self.coils):
            return Response(error="illegal address")
        if address == 0:
            if not value:
                self.coils[0] = False
                self.coils[4] = False
        elif address == 4:
            if not value:
                self.coils[4] = False
        elif address == 5:
            if self.holding[0x47] == 3:
                self.coils[5] = value
        else:
            self.coils[address] = value
        return Response()

    def write_register(self, address: int, value: int) -> Response:
        self.log.append(("register", address, value))
        if not 0 <= address < len(self.holding):
            return Response(error="illegal address")
        if address == 3:
            if not 60 <= value <= 600:
                return Response()
        elif address == 0x49:
            if value > 15:
                return Response()
        elif address in (4, 5, 6):
            if value & 0x7F != 0:
                value &= 0x7F  # bit 7 only exists in sensor mode
        elif address in (7, 8, 9):
            if value != 0:
                return Response()
        elif 0x15 <= address <= 0x46:
            if value != 0:
                return Response()
        elif address == 0x48:
            self.last_reset_command = value
            return Response()  # register reads back as 0
        self.holding[address] = value
        return Response()

    def write_registers(self, address: int, values: list[int]) -> Response:
        for i, v in enumerate(values):
            self.write_register(address + i, v)
        return Response()

    # --- helpers for tests ---
    def set_radio(self, number: int, raw: int) -> None:
        self.holding[0x15 + number - 11] = raw


class FakeClient:
    """Stands in for pymodbus AsyncModbusSerialClient."""

    def __init__(self, module: FakeModule, port: str = "", **kwargs) -> None:
        self.module = module
        self.port = port
        self.kwargs = kwargs
        self.connected = False

    async def connect(self) -> bool:
        self.connected = not self.module.disconnected
        return self.connected

    def close(self) -> None:
        self.connected = False

    async def _read(self, function: str, source: list, address: int, count: int, bits: bool):
        if (gated := self.module.gate(function)) is not None:
            return gated
        if address + count > len(source):
            return Response(error="illegal address")
        chunk = source[address : address + count]
        if bits:
            pad = chunk + [False] * (-len(chunk) % 8)
            return Response(bits=pad)
        return Response(registers=list(chunk))

    async def read_coils(self, address, *, count=1, device_id=1):
        return await self._read("read_coils", self.module.coils, address, count, True)

    async def read_discrete_inputs(self, address, *, count=1, device_id=1):
        return await self._read("read_discrete_inputs", self.module.discrete, address, count, True)

    async def read_holding_registers(self, address, *, count=1, device_id=1):
        return await self._read(
            "read_holding_registers", self.module.holding, address, count, False
        )

    async def read_input_registers(self, address, *, count=1, device_id=1):
        return await self._read("read_input_registers", self.module.input, address, count, False)

    async def write_coil(self, address, value, *, device_id=1):
        if (gated := self.module.gate("write_coil")) is not None:
            return gated
        return self.module.write_coil(address, value)

    async def write_register(self, address, value, *, device_id=1):
        if (gated := self.module.gate("write_register")) is not None:
            return gated
        return self.module.write_register(address, value)

    async def write_registers(self, address, values, *, device_id=1):
        if (gated := self.module.gate("write_registers")) is not None:
            return gated
        return self.module.write_registers(address, values)
