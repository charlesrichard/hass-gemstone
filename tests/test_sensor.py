"""Test the sensor platform: what's playing (pattern or Custom Design) + last-updated."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, CONF_EMAIL, CONF_PASSWORD, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pygemstone import DeviceState, Pattern
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gemstone.const import DOMAIN

DEVICE_ID = "h2-1074-y3w9"


def design_state(name: str = "Front Door", design_id: str = "ad-1") -> DeviceState:
    """A ``currentlyPlaying`` report with a Custom Design lit.

    Shape captured from the live cloud: ``architectural`` is set and the
    ``pattern`` key is absent entirely.
    """
    raw: dict[str, Any] = {
        "id": DEVICE_ID,
        "onState": True,
        "architectural": {
            "id": design_id,
            "name": name,
            "brightness": 255,
            "preview": False,
            "staticColors": [],
        },
    }
    return DeviceState.from_api(raw)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "pw"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id(hass: HomeAssistant, domain: str, suffix: str) -> str:
    ent_reg = er.async_get(hass)
    eid = ent_reg.async_get_entity_id(domain, DOMAIN, f"{DEVICE_ID}_{suffix}")
    assert eid is not None
    return eid


def _coordinator(entry: MockConfigEntry):  # type: ignore[no-untyped-def]
    return entry.runtime_data.coordinators[0]


async def _select(hass: HomeAssistant, suffix: str, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _entity_id(hass, SELECT_DOMAIN, suffix), ATTR_OPTION: option},
        blocking=True,
    )


async def test_now_playing_reports_saved_pattern(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    await _setup(hass)
    state = hass.states.get(_entity_id(hass, SENSOR_DOMAIN, "now_playing"))
    assert state is not None
    assert state.state == "Christmas Classic"
    assert state.attributes["type"] == "pattern"
    assert state.attributes["id"] == "pat-1"
    assert state.attributes["in_saved_folders"] is True


async def test_now_playing_reports_unsaved_pattern(
    hass: HomeAssistant, mock_client: MagicMock, device_state: DeviceState
) -> None:
    """A pattern that isn't in any saved folder is still named (the select can't)."""
    entry = await _setup(hass)
    library_pattern = Pattern.from_api(
        {"id": "lib-99", "name": "All Red 2white", "brightness": 255}
    )
    _coordinator(entry).async_set_updated_data(replace(device_state, pattern=library_pattern))
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, SENSOR_DOMAIN, "now_playing"))
    assert state is not None
    assert state.state == "All Red 2white"
    assert state.attributes["type"] == "pattern"
    assert state.attributes["id"] == "lib-99"
    assert state.attributes["in_saved_folders"] is False


async def test_now_playing_reports_custom_design_from_cloud(
    hass: HomeAssistant, mock_client: MagicMock, mock_device: MagicMock
) -> None:
    """A Custom Design started outside HA (e.g. the app) is picked up from the cloud."""
    mock_device.refresh.return_value = design_state()
    await _setup(hass)

    state = hass.states.get(_entity_id(hass, SENSOR_DOMAIN, "now_playing"))
    assert state is not None
    assert state.state == "Front Door"
    assert state.attributes["type"] == "custom_design"
    assert state.attributes["id"] == "ad-1"
    assert state.attributes["in_saved_folders"] is None

    select = hass.states.get(_entity_id(hass, SELECT_DOMAIN, "custom_design"))
    assert select is not None
    assert select.state == "Front Door"


async def test_switching_between_design_and_pattern(
    hass: HomeAssistant, mock_client: MagicMock, device_state: DeviceState
) -> None:
    entry = await _setup(hass)
    coord = _coordinator(entry)
    sensor_eid = _entity_id(hass, SENSOR_DOMAIN, "now_playing")
    select_eid = _entity_id(hass, SELECT_DOMAIN, "custom_design")

    coord.async_set_updated_data(design_state())
    await hass.async_block_till_done()
    assert hass.states.get(sensor_eid).state == "Front Door"
    assert hass.states.get(select_eid).state == "Front Door"

    coord.async_set_updated_data(device_state)
    await hass.async_block_till_done()
    assert hass.states.get(sensor_eid).state == "Christmas Classic"
    assert hass.states.get(sensor_eid).attributes["type"] == "pattern"
    assert hass.states.get(select_eid).state == "None"


async def test_design_not_in_saved_list_still_named(
    hass: HomeAssistant, mock_client: MagicMock, mock_device: MagicMock
) -> None:
    """A design saved after setup is named by the sensor; the select can't offer it."""
    mock_device.refresh.return_value = design_state("House Number", "ad-new")
    await _setup(hass)
    assert hass.states.get(_entity_id(hass, SENSOR_DOMAIN, "now_playing")).state == (
        "House Number"
    )
    assert hass.states.get(_entity_id(hass, SELECT_DOMAIN, "custom_design")).state == "None"


async def test_applying_design_from_ha_updates_sensor(
    hass: HomeAssistant, mock_client: MagicMock, mock_device: MagicMock
) -> None:
    await _setup(hass)
    await _select(hass, "custom_design", "Front Door")
    state = hass.states.get(_entity_id(hass, SENSOR_DOMAIN, "now_playing"))
    assert state is not None
    assert state.state == "Front Door"
    assert state.attributes["type"] == "custom_design"


async def test_playing_pattern_from_ha_replaces_design(
    hass: HomeAssistant, mock_client: MagicMock, mock_device: MagicMock
) -> None:
    """An optimistic pattern play wins over the stale design still in ``raw``."""
    mock_device.refresh.return_value = design_state()
    await _setup(hass)
    await _select(hass, "folder", "Christmas")
    await _select(hass, "pattern", "Christmas Classic")
    assert hass.states.get(_entity_id(hass, SENSOR_DOMAIN, "now_playing")).state == (
        "Christmas Classic"
    )
    assert hass.states.get(_entity_id(hass, SELECT_DOMAIN, "custom_design")).state == "None"


async def test_now_playing_other_kinds(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    entry = await _setup(hass)
    coord = _coordinator(entry)
    eid = _entity_id(hass, SENSOR_DOMAIN, "now_playing")

    coord.async_set_updated_data(
        DeviceState.from_api({"id": DEVICE_ID, "onState": True, "playlist": {"id": "pl-1"}})
    )
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "Playlist"
    assert hass.states.get(eid).attributes["type"] == "playlist"

    coord.async_set_updated_data(
        DeviceState.from_api({"id": DEVICE_ID, "onState": True, "color": 16711680})
    )
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "Solid color"

    coord.async_set_updated_data(DeviceState.from_api({"id": DEVICE_ID, "onState": False}))
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == STATE_UNKNOWN
    assert hass.states.get(eid).attributes["type"] is None


async def test_last_updated_timestamp(
    hass: HomeAssistant, mock_client: MagicMock, device_state: DeviceState
) -> None:
    entry = await _setup(hass)
    eid = _entity_id(hass, SENSOR_DOMAIN, "last_updated")

    # Fixture state has no lastUpdatedAt.
    state = hass.states.get(eid)
    assert state is not None
    assert state.state == STATE_UNKNOWN

    stamp = datetime(2026, 12, 1, 22, 30, tzinfo=UTC)
    _coordinator(entry).async_set_updated_data(replace(device_state, last_updated_at=stamp))
    await hass.async_block_till_done()

    state = hass.states.get(eid)
    assert state is not None
    assert state.state == stamp.isoformat()
