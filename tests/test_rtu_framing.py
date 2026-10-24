"""Our client against the real pymodbus stack: RTU framing and CRC over loopback TCP.

There is no serial pair on a dev machine, but pymodbus frames RTU identically over TCP, which
checks everything except the serial driver: request kwargs, response parsing, bit padding, timeouts.
"""

import asyncio
import json
import socket

import pytest
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerType
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from custom_components.neptun_modbus.client import (
    NeptunClient,
    NeptunProtocolError,
    NeptunTimeoutError,
)

from .fake_module import SNAPSHOT

pytestmark = pytest.mark.slow


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def rtu_server(socket_enabled):
    snap = json.loads(SNAPSHOT.read_text())
    device = SimDevice(
        id=1,
        simdata=(
            [
                SimData(
                    0, values=[bool(v) for v in snap["coils"]] + [False] * 7, datatype=DataType.BITS
                )
            ],
            [
                SimData(
                    0,
                    values=[bool(v) for v in snap["discrete_inputs"]] + [False] * 5,
                    datatype=DataType.BITS,
                )
            ],
            [SimData(0, values=snap["holding_registers"], datatype=DataType.UINT16)],
            [SimData(0, values=snap["input_registers"], datatype=DataType.UINT16)],
        ),
    )
    port = free_port()
    server = ModbusTcpServer(
        device,
        framer=FramerType.RTU,
        address=("127.0.0.1", port),
        ignore_missing_devices=True,
    )
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0.2)
    yield port
    await server.shutdown()
    task.cancel()


def make_client(port: int, slave: int = 1, timeout: float = 0.3) -> NeptunClient:
    return NeptunClient(
        "unused",
        slave,
        9600,
        timeout=timeout,
        retries=2,
        client_factory=lambda _p, **kw: AsyncModbusTcpClient(
            "127.0.0.1", port=port, framer=FramerType.RTU, timeout=kw["timeout"], retries=0
        ),
    )


async def test_reads_match_snapshot(rtu_server):
    snap = json.loads(SNAPSHOT.read_text())
    client = make_client(rtu_server)
    await client.connect()
    assert await client.read_coils(0, 9) == [bool(v) for v in snap["coils"]]
    assert await client.read_discrete_inputs(0, 3) == [bool(v) for v in snap["discrete_inputs"]]
    assert await client.read_input_registers(0, 10) == snap["input_registers"]
    assert await client.read_holding_registers(0, 74) == snap["holding_registers"]
    await client.close()


async def test_writes_round_trip(rtu_server):
    client = make_client(rtu_server)
    await client.connect()
    await client.write_coil(8, False)
    await client.write_register(0x49, 3)
    await client.write_registers(0x0D, [1, 2])
    assert (await client.read_coils(8, 1)) == [False]
    assert (await client.read_holding_registers(0x49, 1)) == [3]
    assert (await client.read_holding_registers(0x0D, 2)) == [1, 2]
    await client.close()


async def test_unknown_slave_is_exception_not_retried(rtu_server):
    client = make_client(rtu_server, slave=2)
    await client.connect()
    try:
        with pytest.raises(NeptunProtocolError):
            await client.read_input_registers(0, 1)
        assert client.stats.requests == 1
        assert client.stats.exceptions == 1
    finally:
        await client.close()


async def test_silent_peer_times_out_and_retries(socket_enabled):
    async def swallow(reader, writer):
        await reader.read()

    server = await asyncio.start_server(swallow, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = make_client(port, timeout=0.2)
    try:
        await client.connect()
        with pytest.raises(NeptunTimeoutError):
            await client.read_input_registers(0, 1)
        assert client.stats.timeouts == 2
    finally:
        await client.close()
        server.close()
        await server.wait_closed()
