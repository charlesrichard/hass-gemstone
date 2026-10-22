"""Test the select platform: cascading folder + pattern pickers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gemstone.const import DOMAIN

DEVICE_ID = "h2-1074-y3w9"


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


def _pattern_entity_id(hass: HomeAssistant) -> str:
    ent_reg = er.async_get(hass)
    eid = ent_reg.async_get_entity_id(SELECT_DOMAIN, DOMAIN, f"{DEVICE_ID}_pattern")
    assert eid is not None
    return eid


def _folder_entity_id(hass: HomeAssistant) -> str:
    ent_reg = er.async_get(hass)
    eid = ent_reg.async_get_entity_id(SELECT_DOMAIN, DOMAIN, f"{DEVICE_ID}_folder")
    assert eid is not None
    return eid


async def test_folder_options_include_all_folders(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    await _setup(hass)
    state = hass.states.get(_folder_entity_id(hass))
    assert state is not None
    assert sorted(state.attributes["options"]) == ["Christmas", "Halloween"]


async def test_folder_defaults_to_current_pattern_folder(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Without an explicit pick, the folder dropdown points at the playing pattern's folder."""
    await _setup(hass)
    state = hass.states.get(_folder_entity_id(hass))
    assert state is not None
    # device's currently-playing pattern is "Christmas Classic" (in Christmas)
    assert state.state == "Christmas"


async def test_pattern_options_only_include_active_folder(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """The pattern dropdown shows only patterns from the active folder.

    The first option is always the ``Select a pattern…`` placeholder so
    HA has something sensible to display when the device's pattern
    isn't in the active folder.
    """
    await _setup(hass)
    state = hass.states.get(_pattern_entity_id(hass))
    assert state is not None
    # default active folder is Christmas -> placeholder + Christmas patterns
    assert sorted(state.attributes["options"]) == [
        "Christmas Classic",
        "Select a pattern…",
    ]


async def test_pattern_current_option_matches_active_pattern(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    await _setup(hass)
    state = hass.states.get(_pattern_entity_id(hass))
    assert state is not None
    assert state.state == "Christmas Classic"


async def test_switching_folder_changes_pattern_options(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """Selecting a different folder re-populates the pattern dropdown."""
    await _setup(hass)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _folder_entity_id(hass), ATTR_OPTION: "Halloween"},
        blocking=True,
    )
    folder_state = hass.states.get(_folder_entity_id(hass))
    assert folder_state is not None
    assert folder_state.state == "Halloween"

    pattern_state = hass.states.get(_pattern_entity_id(hass))
    assert pattern_state is not None
    assert sorted(pattern_state.attributes["options"]) == [
        "Halloween",
        "Select a pattern…",
        "Spooky",
    ]
    # The device is still playing "Christmas Classic" (not in Halloween folder),
    # so the pattern dropdown shows the placeholder rather than "unknown".
    assert pattern_state.state == "Select a pattern…"


async def test_switching_folder_does_not_call_device(
    hass: HomeAssistant, mock_client: MagicMock, mock_device: MagicMock
) -> None:
    """Folder selection is pure UI state -- no device or cloud call."""
    await _setup(hass)
    mock_device.refresh.reset_mock()
    mock_device.play_pattern.reset_mock()
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _folder_entity_id(hass), ATTR_OPTION: "Halloween"},
        blocking=True,
    )
    mock_device.refresh.assert_not_awaited()
    mock_device.play_pattern.assert_not_awaited()


async def test_select_pattern_from_active_folder_plays_it(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_device: MagicMock,
) -> None:
    await _setup(hass)
    # Switch folder first so the Halloween patterns are visible.
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _folder_entity_id(hass), ATTR_OPTION: "Halloween"},
        blocking=True,
    )
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _pattern_entity_id(hass), ATTR_OPTION: "Spooky"},
        blocking=True,
    )
    mock_device.play_pattern.assert_awaited_once()
    played = mock_device.play_pattern.call_args.args[0]
    assert played.name == "Spooky"


async def test_select_pattern_optimistically_updates_state(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_device: MagicMock,
) -> None:
    """After selecting a pattern, state must reflect the new pick immediately.

    Regression test for the flicker fix: the cloud's currentlyPlaying
    endpoint lags 30-60s behind the device, so a post-action refresh
    used to return the previous pattern and snap the dropdown back.
    The fix is an optimistic local update -- no extra refresh.
    """
    await _setup(hass)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _folder_entity_id(hass), ATTR_OPTION: "Halloween"},
        blocking=True,
    )
    mock_device.refresh.reset_mock()
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _pattern_entity_id(hass), ATTR_OPTION: "Spooky"},
        blocking=True,
    )
    assert hass.states.get(_pattern_entity_id(hass)).state == "Spooky"
    mock_device.refresh.assert_not_awaited()


async def test_select_pattern_not_in_active_folder_is_rejected(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_device: MagicMock,
) -> None:
    """A pattern name from a different folder must not play anything.

    HA's select platform validates against ``entity.options`` before
    handing off to ``async_select_option``, so submitting a stale
    option (e.g., one from a folder the user already navigated away
    from) raises ``ServiceValidationError`` and the device is never
    touched.
    """
    await _setup(hass)
    # active folder defaults to Christmas; ask for a Halloween-only pattern.
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: _pattern_entity_id(hass), ATTR_OPTION: "Spooky"},
            blocking=True,
        )
    mock_device.play_pattern.assert_not_awaited()


async def test_selecting_placeholder_is_noop(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_device: MagicMock,
) -> None:
    """Selecting the ``Select a pattern…`` placeholder must not play anything."""
    await _setup(hass)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: _pattern_entity_id(hass),
            ATTR_OPTION: "Select a pattern…",
        },
        blocking=True,
    )
    mock_device.play_pattern.assert_not_awaited()


def _custom_design_entity_id(hass: HomeAssistant) -> str:
    ent_reg = er.async_get(hass)
    eid = ent_reg.async_get_entity_id(
        SELECT_DOMAIN, DOMAIN, f"{DEVICE_ID}_custom_design"
    )
    assert eid is not None
    return eid


async def test_custom_design_options_include_saved_designs(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    await _setup(hass)
    state = hass.states.get(_custom_design_entity_id(hass))
    assert state is not None
    assert sorted(state.attributes["options"]) == ["Front Door", "None"]


async def test_select_custom_design_applies_it(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_device: MagicMock,
) -> None:
    await _setup(hass)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _custom_design_entity_id(hass), ATTR_OPTION: "Front Door"},
        blocking=True,
    )
    mock_device.apply_architectural_design.assert_awaited_once()
    applied = mock_device.apply_architectural_design.call_args.args[0]
    assert applied.name == "Front Door"


async def test_select_custom_design_updates_current_option(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_device: MagicMock,
) -> None:
    """After applying a design the picker shows it instead of "None".

    The state is updated optimistically until the next poll reports the
    design under ``currentlyPlaying.architectural``.
    """
    await _setup(hass)
    eid = _custom_design_entity_id(hass)
    assert hass.states.get(eid).state == "None"
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: eid, ATTR_OPTION: "Front Door"},
        blocking=True,
    )
    assert hass.states.get(eid).state == "Front Door"
    # Selecting the placeholder can't "un-play" a design: the lit design stays.
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: eid, ATTR_OPTION: "None"},
        blocking=True,
    )
    assert hass.states.get(eid).state == "Front Door"


async def test_selecting_custom_design_placeholder_is_noop(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_device: MagicMock,
) -> None:
    await _setup(hass)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: _custom_design_entity_id(hass), ATTR_OPTION: "None"},
        blocking=True,
    )
    mock_device.apply_architectural_design.assert_not_awaited()


async def test_no_custom_design_entity_when_none_saved(
    hass: HomeAssistant, mock_client: MagicMock, mock_device: MagicMock
) -> None:
    """No Custom Design select entity is created if the device has none saved."""
    mock_device.architectural_designs.return_value = []
    await _setup(hass)
    ent_reg = er.async_get(hass)
    eid = ent_reg.async_get_entity_id(
        SELECT_DOMAIN, DOMAIN, f"{DEVICE_ID}_custom_design"
    )
    assert eid is None

