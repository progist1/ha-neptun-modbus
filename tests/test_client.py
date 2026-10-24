import pytest

from custom_components.neptun_modbus.client import (
    NeptunClient,
    NeptunConnectionError,
    NeptunProtocolError,
    NeptunTimeoutError,
)

from .fake_module import FakeClient


@pytest.fixture
def client(module):
    c = NeptunClient(
        "/dev/ttyUSB0",
        1,
        9600,
        retries=3,
        client_factory=lambda p, **kw: FakeClient(module, p, **kw),
    )
    return c


async def test_read_ok(client, module):
    await client.connect()
    assert await client.read_coils(0, 9) == module.coils
    assert await client.read_holding_registers(0x15, 4) == [141, 141, 141, 142]
    assert client.stats.timeouts == 0


async def test_retry_recovers(client, module):
    await client.connect()
    module.fail_next = 2
    assert (await client.read_input_registers(9, 1)) == [100]
    assert client.stats.timeouts == 2


async def test_timeout_after_retries(client, module):
    await client.connect()
    module.silent = True
    with pytest.raises(NeptunTimeoutError):
        await client.read_input_registers(0, 1)
    assert client.stats.timeouts == 3


async def test_exception_response_not_retried(client, module):
    await client.connect()
    module.exception_functions = {"read_coils"}
    with pytest.raises(NeptunProtocolError):
        await client.read_coils(0, 1)
    assert client.stats.exceptions == 1
    assert client.stats.requests == 1


async def test_port_lost(client, module):
    await client.connect()
    module.disconnected = True
    with pytest.raises(NeptunConnectionError):
        await client.read_coils(0, 1)
    assert not client.connected


async def test_connect_failure(client, module):
    module.disconnected = True
    with pytest.raises(NeptunConnectionError):
        await client.connect()


async def test_reconnects_when_port_returns(client, module):
    await client.connect()
    module.disconnected = True
    with pytest.raises(NeptunConnectionError):
        await client.read_coils(0, 1)
    module.disconnected = False
    assert len(await client.read_coils(0, 9)) == 9
    assert client.stats.reconnects == 1


async def test_writes(client, module):
    await client.connect()
    await client.write_coil(8, False)
    await client.write_register(0x49, 7)
    await client.write_registers(7, [0, 0, 0])
    assert module.coils[8] is False
    assert module.holding[0x49] == 7


async def test_pause_blocks_requests_and_releases_the_port(client, module):
    await client.connect()
    await client.pause()
    assert not client.connected
    with pytest.raises(NeptunConnectionError):
        await client.read_coils(0, 1)
    client.resume()
    assert len(await client.read_coils(0, 9)) == 9  # reconnects by itself


async def test_no_sleep_after_last_attempt(client, module, monkeypatch):
    from custom_components.neptun_modbus import client as client_module

    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(client_module, "RETRY_PAUSE", 0.2)
    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    await client.connect()
    module.silent = True
    with pytest.raises(NeptunTimeoutError):
        await client.read_coils(0, 1)
    assert len(sleeps) == 2  # 3 attempts -> pauses only between them
