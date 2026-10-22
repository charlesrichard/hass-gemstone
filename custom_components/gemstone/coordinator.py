"""DataUpdateCoordinator for Gemstone devices."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pygemstone import (
    ArchitecturalDesign,
    Device,
    DeviceState,
    GemstoneAuthError,
    GemstoneConnectionError,
    GemstoneError,
)

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

KIND_PATTERN = "pattern"
KIND_CUSTOM_DESIGN = "custom_design"
KIND_PLAYLIST = "playlist"
KIND_COLOR = "color"


@dataclass(frozen=True, slots=True)
class NowPlaying:
    """What the controller is playing, as ``currentlyPlaying`` reports it."""

    kind: str
    id: str | None = None
    name: str | None = None


def now_playing(data: DeviceState | None) -> NowPlaying | None:
    """Work out what is playing from a ``currentlyPlaying`` report.

    The cloud reports exactly one of these at a time: a folder ``pattern``
    (``architectural`` is null), or a Custom Design under ``architectural``
    (the ``pattern`` key is absent). ``data.pattern`` is checked first so an
    optimistic pattern update wins over a stale ``architectural`` in ``raw``.
    ``playlist`` and ``color`` are handled defensively; their payload shapes
    haven't been captured yet.
    """
    if data is None:
        return None
    if data.pattern is not None:
        return NowPlaying(KIND_PATTERN, data.pattern.id or None, data.pattern.name or None)
    raw = data.raw or {}
    design = raw.get("architectural")
    if isinstance(design, dict):
        return NowPlaying(
            KIND_CUSTOM_DESIGN, design.get("id") or None, design.get("name") or None
        )
    playlist = raw.get("playlist")
    if isinstance(playlist, dict):
        return NowPlaying(KIND_PLAYLIST, playlist.get("id") or None, playlist.get("name") or None)
    if raw.get("color") is not None:
        return NowPlaying(KIND_COLOR)
    return None


class GemstoneCoordinator(DataUpdateCoordinator[DeviceState]):
    """Polling coordinator for a single Gemstone controller.

    One coordinator per device; the integration creates one for each
    Gemstone device discovered on the account at setup time.

    ``active_folder`` is UI-only state shared between the folder picker
    and pattern picker entities. It's None until the user explicitly
    selects a folder, in which case the picker entities fall back to
    "the folder of the currently playing pattern" via the catalogue's
    reverse index.

    Which Custom Design is lit comes from the cloud: ``currentlyPlaying``
    carries it under ``architectural`` (see :func:`now_playing`).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: Device,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {device.id}",
            update_interval=DEFAULT_SCAN_INTERVAL,
            config_entry=entry,
        )
        self.device = device
        self.active_folder: str | None = None
        self.architectural_designs: list[ArchitecturalDesign] = []

    async def async_refresh_architectural_designs(self) -> None:
        """Fetch this device's saved "Custom Designs" (Quick Access looks).

        Best-effort: an error here shouldn't block integration setup, so
        callers should be prepared for the list to stay empty if the
        cloud call fails.
        """
        self.architectural_designs = await self.device.architectural_designs()

    def set_active_folder(self, folder: str | None) -> None:
        """Update the active folder and notify listening entities.

        The pattern picker reads ``coordinator.active_folder`` to
        decide which folder's patterns to expose; calling
        ``async_update_listeners`` re-renders both selects so the
        pattern dropdown's options switch in lockstep.
        """
        self.active_folder = folder
        self.async_update_listeners()

    @property
    def now_playing(self) -> NowPlaying | None:
        return now_playing(self.data)

    def async_set_playing_design(self, design: ArchitecturalDesign) -> None:
        """Optimistically record that ``design`` is now lit.

        Mirrors the shape ``currentlyPlaying`` reports for a Custom Design
        (``architectural`` set, no ``pattern``); the next poll reconciles.
        """
        data = self.data
        if data is None:
            return
        raw = {**(data.raw or {}), "architectural": {"id": design.id, "name": design.name}}
        raw.pop("pattern", None)
        self.async_set_updated_data(replace(data, pattern=None, raw=raw))

    async def _async_update_data(self) -> DeviceState:
        try:
            return await self.device.refresh()
        except GemstoneAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GemstoneConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except GemstoneError as err:
            raise UpdateFailed(str(err)) from err
