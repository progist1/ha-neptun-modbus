<img src="custom_components/neptun_modbus/brand/icon.png" width="96" align="right" alt="">

# Neptun for Home Assistant

Integration for the Neptun valve control module (water leak protection): sensors, valves, UPS and module
settings in Home Assistant. The module connects over RS-485 (Modbus RTU).

This is an unofficial integration and is not affiliated with the manufacturer. The name "Neptun" only says
which device it works with.

На русском: [README.md](README.md)

## Features

- Shows leaks from radio sensors and from wired lines.
- Opens and closes the valves.
- Shows UPS charge, module errors and the state of the valve lines.
- Finds radio sensors on its own. Each one gets a device with battery level and signal strength.
- Lets you change module settings: backlight, brightness, siren time, relay mode, child lock and more.
- Mutes the siren and clears a leak with buttons.
- If the module stops answering, the "Connection" entity turns off, and after 5 minutes a message appears
  in Repairs.

## Requirements

- Home Assistant 2026.10 or newer.
- An RS-485 adapter connected to the machine running Home Assistant. In Docker or Kubernetes, pass the device
  through, preferably by its stable path `/dev/serial/by-id/...`.
- Factory module settings: address 1, 9600 baud.

## Installation

With HACS: add this repository as a custom repository (type "Integration"), install "Neptun Modbus" and restart
Home Assistant.

Manually: copy the `custom_components/neptun_modbus` folder into the `custom_components` folder of your configuration
and restart.

Then go to *Settings → Devices & services → Add integration → Neptun Modbus*. Choose the port, address and
baud rate. The setup checks that a Neptun module really answers on the other end.

## Options

In the integration options you can change:

- how often the module is polled (every 5 seconds by default);
- how long to wait for an answer and how many times to retry;
- how many valve lines are connected (one by default; set 2 if you have two).

## Careful with buttons

- Valves open and close at once, without confirmation.
- The "Reboot module" and "Remove sensor" buttons are hidden. Enable them in the entity settings if you need them.
- Factory reset is available only as the service `neptun_modbus.factory_reset`, and you must set `confirm: true`.
  It also resets the address and the communication settings, so the module may stop answering. You can then
  connect with the factory parameters.
- The module's own address and baud rate are never changed from Home Assistant.

## Good to know

- "Reset leak" works when the sensor is dry. While it is wet, the module raises the leak again.
  "Mute siren" silences the sound in any case.
- Every wired line has its own device. The module does not tell whether a sensor is connected to a line, so
  disable unused lines yourself: device page, menu, "Disable device". Firmware 0.2.0 does not keep the line
  mode "Not used" and switches it back to "Sensor" at once.
- The module does not count a simple contact sensor. "Sensor count" and "Close valves on wired sensor loss"
  do not work with it, but the leak itself is detected.
- A radio sensor that lost its connection shows "Unavailable", not "Dry": no data does not mean no water.
  The exception is a sensor that had already reported a leak: that stays "Leak".
- The module reports the battery of radio sensors in four steps, so 0, 33, 67 and 100 percent is an estimate.
- The valve state comes from the controller's command ("open or opening" or "closed or closing"), not from a
  position sensor. The actual position is shown by "Valve line" when feedback is enabled.
- "Link state" shows whether the module answers fully, partially (some data cannot be read) or not at all.
  The reasons per data block are in the attributes and in the diagnostics.
- The module ignores some writes, for example "Relay" outside the manual mode. Home Assistant always shows
  what the module accepted.

## For developers

```
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests need no hardware: they include a module simulator with the write rules from the documentation and a
run against the real pymodbus stack. The register map is in `custom_components/neptun_modbus/registers.py`.

Check against a real module without Home Assistant (the port must be free):

```
python3 tools/live_probe.py --port /dev/ttyUSB0 --slave 1 --baud 9600
```
