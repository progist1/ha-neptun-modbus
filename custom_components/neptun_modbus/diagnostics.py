"""Diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import NeptunConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NeptunConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    stats = coordinator.client.stats
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "link": {
            "ok": coordinator.link_ok,
            "consecutive_failures": coordinator.consecutive_failures,
            "last_success": coordinator.last_success.isoformat()
            if coordinator.last_success
            else None,
            "last_error": coordinator.last_error,
            "requests": stats.requests,
            "timeouts": stats.timeouts,
            "exceptions": stats.exceptions,
            "reconnects": stats.reconnects,
        },
        "radio_indexes": sorted(coordinator.radio_indexes),
        "blocks_ok": dict(data.ok) if data else None,
        "registers": (
            {
                "coils": data.coils,
                "discrete_inputs": data.discrete,
                "holding": data.holding,
                "input": data.input,
            }
            if data
            else None
        ),
    }
