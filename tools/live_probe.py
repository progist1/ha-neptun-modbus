#!/usr/bin/env python3
"""Read-only probe of a real Neptun module through the integration's own client.

Needs only pymodbus (no Home Assistant). Only read requests are sent, never writes.
The serial port must not be held by another process (stop Home Assistant first).

    python3 tools/live_probe.py --port /dev/ttyUSB0 --slave 1 --baud 9600 [--cycles 20] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "neptun_modbus"


def load(name: str):
    """Import client.py / registers.py by path: the package __init__ needs Home Assistant."""
    spec = importlib.util.spec_from_file_location(f"neptun_probe_{name}", PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


client_mod = load("client")
reg = load("registers")


async def read_all(client) -> dict:
    return {
        "coils": await client.read_coils(0, reg.COIL_COUNT),
        "discrete_inputs": await client.read_discrete_inputs(0, reg.DI_COUNT),
        "input_registers": await client.read_input_registers(0, reg.IR_COUNT),
        "holding_registers": await client.read_holding_registers(0, reg.HR_COUNT),
    }


def describe(d: dict) -> None:
    ir, hr, co = d["input_registers"], d["holding_registers"], d["coils"]
    print(f"device type   0x{ir[0]:04X} ({'Neptun' if ir[0] == reg.DEVICE_TYPE else 'UNKNOWN'})")
    print(f"hardware/fw   {ir[1]} / {reg.decode_firmware(ir[2])}")
    print(f"leak={co[0]} valves_open={co[1]} feedback={co[2]} siren={co[4]} relay={co[5]}")
    print(
        f"valves power={d['discrete_inputs'][0]} ups present={d['discrete_inputs'][1]} on ups={d['discrete_inputs'][2]}"
    )
    print(
        f"valve line 1 = {reg.decode_valve_line(ir[3], 1)}, line 2 = {reg.decode_valve_line(ir[3], 2)}"
    )
    print(f"ups charge    {ir[9]}%   errors: {reg.decode_errors(ir[8]) or 'none'}")
    for n in range(reg.WIRED_LINES):
        cfg = hr[reg.HR_WIRED_CONFIG + n]
        print(
            f"wired line {n + 1}: mode={reg.WiredMode(cfg & 0x7F).name.lower()} "
            f"feedback={bool(cfg & 0x80)} state={bool(ir[4] >> n & 1)} "
            f"saved={ir[5 + n]} diff={reg.to_signed16(hr[reg.HR_WIRED_DIFF + n])}"
        )
    for i in range(reg.RADIO_COUNT):
        r = reg.decode_radio(i, hr[reg.HR_RADIO_FIRST + i])
        if r:
            print(
                f"radio {r.number}: leak={r.leak} lost={r.lost} "
                f"battery={r.battery_percent}% rssi={r.rssi}"
            )
    print(
        f"mode={hr[reg.HR_MODE]} relay_mode={hr[reg.HR_RELAY_MODE]} brightness={hr[reg.HR_BRIGHTNESS]}"
    )


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--slave", type=int, default=1)
    p.add_argument("--baud", type=int, default=9600)
    p.add_argument("--cycles", type=int, default=1, help="repeat the full read N times for timing")
    p.add_argument("--json", action="store_true", help="print raw registers as JSON")
    a = p.parse_args()

    client = client_mod.NeptunClient(a.port, a.slave, a.baud)
    try:
        try:
            await client.connect()
        except client_mod.NeptunConnectionError as err:
            print(f"cannot open the port: {err}", file=sys.stderr)
            return 2
        first = None
        durations = []
        errors = 0
        for _ in range(a.cycles):
            t0 = time.monotonic()
            try:
                data = await read_all(client)
            except client_mod.NeptunError as err:
                errors += 1
                print(f"cycle failed: {err}", file=sys.stderr)
                continue
            durations.append(time.monotonic() - t0)
            first = first or data
        if first is None:
            print("no successful cycle", file=sys.stderr)
            return 1
        print(json.dumps(first) if a.json else "", end="\n" if a.json else "")
        if not a.json:
            describe(first)
        if a.cycles > 1:
            print(
                f"\n{len(durations)}/{a.cycles} cycles ok, cycle time min/avg/max "
                f"{min(durations):.2f}/{sum(durations) / len(durations):.2f}/{max(durations):.2f} s; "
                f"timeouts={client.stats.timeouts} exceptions={client.stats.exceptions}"
            )
        return 1 if errors else 0
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
