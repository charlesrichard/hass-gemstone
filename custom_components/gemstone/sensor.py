"""Sensor platform: what the controller is playing, as the cloud reports it.

The ``select.<controller>_pattern`` entity can only name a pattern that is
saved in one of the account's folders, so anything played from Gemstone's
preset library (or otherwise not saved) shows as its placeholder. The
"Now playing" sensor reports the raw ``currentlyPlaying`` contents instead,
unfiltered by the folder catalogue, including which Custom Design is lit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GemstoneConfigEntry, PatternCatalogue
from .coordinator import (
    KIND_COLOR,
    KIND_CUSTOM_DESIGN,
    KIND_PATTERN,
    KIND_PLAYLIST,
    GemstoneCoordinator,
)
from .entity import GemstoneEntity

# State used when the cloud reports something without a name.
_FALLBACK_NAMES = {
    KIND_PATTERN: "Pattern",
    KIND_CUSTOM_DESIGN: "Custom design",
    KIND_PLAYLIST: "Playlist",
    KIND_COLOR: "Solid color",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GemstoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    catalogue = entry.runtime_data.catalogue
    entities: list[SensorEntity] = []
    for coord in entry.runtime_data.coordinators:
        entities.append(GemstoneNowPlayingSensor(coord, catalogue))
        entities.append(GemstoneLastUpdatedSensor(coord))
    async_add_entities(entities)


class GemstoneNowPlayingSensor(GemstoneEntity, SensorEntity):
    """Name of the pattern or Custom Design the cloud reports as playing.

    This is the last thing played; it stays put when the lights are turned
    off, so pair it with the light entity's on/off state.
    """

    _attr_translation_key = "now_playing"
    _attr_icon = "mdi:string-lights"

    def __init__(
        self,
        coordinator: GemstoneCoordinator,
        catalogue: PatternCatalogue,
    ) -> None:
        super().__init__(coordinator, "now_playing")
        self._catalogue = catalogue

    @property
    def native_value(self) -> str | None:
        playing = self.coordinator.now_playing
        if playing is None:
            return None
        return playing.name or _FALLBACK_NAMES.get(playing.kind, playing.kind)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        playing = self.coordinator.now_playing
        if playing is None:
            return {"type": None, "id": None, "in_saved_folders": None}
        in_saved: bool | None = None
        if playing.kind == KIND_PATTERN:
            in_saved = playing.id in self._catalogue.pattern_to_folder
        return {"type": playing.kind, "id": playing.id, "in_saved_folders": in_saved}


class GemstoneLastUpdatedSensor(GemstoneEntity, SensorEntity):
    """The cloud's ``lastUpdatedAt`` for the controller's playback state.

    Advances on every command (play, replay of the same pattern, brightness,
    on/off), so it can be used to notice activity that changes nothing else.
    """

    _attr_translation_key = "last_updated"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GemstoneCoordinator) -> None:
        super().__init__(coordinator, "last_updated")

    @property
    def native_value(self) -> datetime | None:
        data = self.coordinator.data
        return data.last_updated_at if data is not None else None
