"""Select platform: cascading Folder -> Pattern pickers."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GemstoneConfigEntry, PatternCatalogue
from .coordinator import KIND_CUSTOM_DESIGN, GemstoneCoordinator
from .entity import GemstoneEntity

# Shown as the pattern dropdown's current value when the device's playing
# pattern isn't in the active folder (e.g., right after the user switches
# folders without picking a pattern). It's also listed as the first option
# so HA's service-call validator doesn't reject it; selecting it is a no-op.
PATTERN_PLACEHOLDER = "Select a pattern…"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GemstoneConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    catalogue = entry.runtime_data.catalogue
    entities: list[SelectEntity] = []
    for coord in entry.runtime_data.coordinators:
        entities.append(GemstoneFolderSelect(coord, catalogue))
        entities.append(GemstonePatternSelect(coord, catalogue))
        if coord.architectural_designs:
            entities.append(GemstoneCustomDesignSelect(coord))
    async_add_entities(entities)


def _folder_of_current_pattern(
    coordinator: GemstoneCoordinator, catalogue: PatternCatalogue
) -> str | None:
    """Return the folder the device's currently-playing pattern lives in.

    Falls through to the first folder alphabetically if the cloud
    didn't report a recognised pattern.id.
    """
    data = coordinator.data
    if data is not None and data.pattern is not None and data.pattern.id:
        folder = catalogue.pattern_to_folder.get(data.pattern.id)
        if folder is not None:
            return folder
    folders = catalogue.folders
    return folders[0] if folders else None


class GemstoneFolderSelect(GemstoneEntity, SelectEntity):
    """Pick which pattern folder the pattern dropdown is browsing."""

    _attr_translation_key = "folder"
    _attr_icon = "mdi:folder-multiple"

    def __init__(
        self,
        coordinator: GemstoneCoordinator,
        catalogue: PatternCatalogue,
    ) -> None:
        super().__init__(coordinator, "folder")
        self._catalogue = catalogue
        self._attr_options = catalogue.folders

    @property
    def current_option(self) -> str | None:
        if self.coordinator.active_folder in self._catalogue.by_folder:
            return self.coordinator.active_folder
        return _folder_of_current_pattern(self.coordinator, self._catalogue)

    async def async_select_option(self, option: str) -> None:
        if option not in self._catalogue.by_folder:
            return
        # Pure UI state -- no device call, no cloud round-trip.
        self.coordinator.set_active_folder(option)


class GemstonePatternSelect(GemstoneEntity, SelectEntity):
    """Pick the active Gemstone pattern from within the active folder."""

    _attr_translation_key = "pattern"
    _attr_icon = "mdi:string-lights"

    def __init__(
        self,
        coordinator: GemstoneCoordinator,
        catalogue: PatternCatalogue,
    ) -> None:
        super().__init__(coordinator, "pattern")
        self._catalogue = catalogue

    def _effective_folder(self) -> str | None:
        if self.coordinator.active_folder in self._catalogue.by_folder:
            return self.coordinator.active_folder
        return _folder_of_current_pattern(self.coordinator, self._catalogue)

    @property
    def options(self) -> list[str]:
        folder = self._effective_folder()
        if folder is None:
            return [PATTERN_PLACEHOLDER]
        return [PATTERN_PLACEHOLDER, *self._catalogue.patterns_in(folder)]

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.pattern is None:
            return PATTERN_PLACEHOLDER
        name = data.pattern.name
        if not name:
            return PATTERN_PLACEHOLDER
        folder = self._effective_folder()
        if folder is None or name not in self._catalogue.by_folder.get(folder, {}):
            return PATTERN_PLACEHOLDER
        return name

    async def async_select_option(self, option: str) -> None:
        if option == PATTERN_PLACEHOLDER:
            return
        folder = self._effective_folder()
        if folder is None:
            return
        pattern = self._catalogue.get(folder, option)
        if pattern is None:
            return
        await self.coordinator.device.play_pattern(pattern)
        # Optimistic local update: the cloud's ``currentlyPlaying`` endpoint
        # lags ~30-60s behind the device, so refreshing immediately would
        # report the previous pattern and snap the UI back. Publish the
        # expected pattern locally; the next scheduled poll reconciles.
        data = self.coordinator.data
        if data is not None:
            self.coordinator.async_set_updated_data(replace(data, pattern=pattern))


# Shown when no Custom Design is lit (e.g. the device is playing a folder
# pattern instead), and listed first so HA's service-call validator accepts
# it as a valid "no selection" option. Selecting it is a no-op.
CUSTOM_DESIGN_PLACEHOLDER = "None"


class GemstoneCustomDesignSelect(GemstoneEntity, SelectEntity):
    """Pick one of the device's saved "Custom Designs" (Quick Access looks).

    Unlike folder patterns, these are stored per-device rather than
    per-homegroup (see ``pygemstone.ArchitecturalDesign``), so this is a
    single flat picker with no folder cascade.
    """

    _attr_translation_key = "custom_design"
    _attr_icon = "mdi:palette-swatch"

    def __init__(self, coordinator: GemstoneCoordinator) -> None:
        super().__init__(coordinator, "custom_design")

    @property
    def options(self) -> list[str]:
        names = sorted({d.name for d in self.coordinator.architectural_designs if d.name})
        return [CUSTOM_DESIGN_PLACEHOLDER, *names]

    @property
    def current_option(self) -> str | None:
        playing = self.coordinator.now_playing
        if (
            playing is not None
            and playing.kind == KIND_CUSTOM_DESIGN
            and playing.name in self.options
        ):
            return playing.name
        return CUSTOM_DESIGN_PLACEHOLDER

    async def async_select_option(self, option: str) -> None:
        if option == CUSTOM_DESIGN_PLACEHOLDER:
            return
        design = next(
            (d for d in self.coordinator.architectural_designs if d.name == option),
            None,
        )
        if design is None:
            return
        await self.coordinator.device.apply_architectural_design(design)
        # Optimistic local update until the next poll picks the design up
        # from ``currentlyPlaying``.
        self.coordinator.async_set_playing_design(design)
