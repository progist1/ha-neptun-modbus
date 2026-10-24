import json
from pathlib import Path

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

PKG = Path(__file__).parent.parent / "custom_components" / "neptun_modbus"


def flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}"


def load(lang):
    return json.loads((PKG / "translations" / f"{lang}.json").read_text(encoding="utf-8"))


def test_translations_have_same_keys():
    assert set(flatten(load("en"))) == set(flatten(load("ru")))


def test_services_yaml_matches_translations():
    import yaml

    services = yaml.safe_load((PKG / "services.yaml").read_text())
    assert set(services) == set(load("en")["services"])


async def test_every_entity_has_a_translation(hass, setup):
    en = load("en")["entity"]
    for entry in er.async_entries_for_config_entry(er.async_get(hass), setup.entry_id):
        assert entry.translation_key, entry.entity_id
        assert entry.translation_key in en[entry.domain], entry.entity_id


async def test_diagnostics(hass, hass_client, setup):
    result = await get_diagnostics_for_config_entry(hass, hass_client, setup)
    assert result["link"]["ok"] is True
    assert result["radio_indexes"] == [0, 1, 2, 3]
    assert result["registers"]["input"][0] == 0xCB43
    assert len(result["registers"]["holding"]) == 74
    assert result["blocks_ok"] == {"coils": True, "discrete": True, "holding": True, "input": True}
