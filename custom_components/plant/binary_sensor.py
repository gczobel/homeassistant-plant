"""Global problem binary sensor for the plant integration.

Registered at domain level (like the ws_get_info websocket API) rather than
per-entry, since this is a single global sensor not tied to any specific plant.

Uses discovery.async_load_platform (same pattern as the core Energy integration
and Adaptive Lighting). This means the sensor does NOT support unloading — it
persists until HA restarts even if all plant config entries are removed. This is
an inherent limitation of domain-level entities not owned by a config entry.
"""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_PROBLEM
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ATTR_PLANT,
    ATTR_PLANTS_WITH_PROBLEMS,
    DATA_GLOBAL_PROBLEM_SENSOR,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the global plant problem binary sensor via discovery."""
    if discovery_info is None:
        return
    sensor = PlantMonitorProblemSensor(hass)
    async_add_entities([sensor])
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][DATA_GLOBAL_PROBLEM_SENSOR] = sensor


class PlantMonitorProblemSensor(BinarySensorEntity):
    """Binary sensor that is on when any plant has problems."""

    _attr_has_entity_name = False
    _attr_name = "Plant problems"
    _attr_unique_id = "plant_monitor_global_problems"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the global problem sensor."""
        self.hass = hass
        self._tracked_entity_ids: set[str] = set()
        self._remove_listener: callable | None = None

    async def async_added_to_hass(self) -> None:
        """Register state change listener when added to hass."""
        # Register removal once; the wrapper delegates to whatever the
        # current listener is, so _refresh_tracked_plants can swap it
        # without accumulating stale async_on_remove callbacks.
        self.async_on_remove(
            lambda: self._remove_listener() if self._remove_listener else None
        )
        self._refresh_tracked_plants()

    @callback
    def _refresh_tracked_plants(self) -> None:
        """Rebuild the state-change listener to track all current plants.

        Called on startup and whenever a new plant is registered, so that
        plants added after initial setup are also tracked. Without this,
        only plants that existed when the sensor was first loaded would
        trigger updates.
        """
        current_ids = {
            entry_data[ATTR_PLANT].entity_id
            for entry_data in self.hass.data.get(DOMAIN, {}).values()
            if isinstance(entry_data, dict) and ATTR_PLANT in entry_data
        }

        if current_ids == self._tracked_entity_ids:
            return

        # Tear down old listener before creating a new one
        if self._remove_listener is not None:
            self._remove_listener()

        self._tracked_entity_ids = current_ids

        @callback
        def _plant_state_changed(event: Event) -> None:
            """Handle plant state changes."""
            self.async_write_ha_state()

        if current_ids:
            self._remove_listener = async_track_state_change_event(
                self.hass, list(current_ids), _plant_state_changed
            )
        else:
            self._remove_listener = None

    @property
    def is_on(self) -> bool:
        """Return true if any plant has problems."""
        for entry_data in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            plant = entry_data.get(ATTR_PLANT)
            if (
                plant is not None
                and getattr(plant, "_attr_state", None) == STATE_PROBLEM
            ):
                return True
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Return details about which plants have problems."""
        plants_with_problems = []
        total_problems = 0
        total_plants = 0
        entity_reg = er.async_get(self.hass)

        for entry_data in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            plant = entry_data.get(ATTR_PLANT)
            if plant is None:
                continue
            total_plants += 1
            plant_problems = getattr(plant, "_problems", [])
            if plant_problems:
                problem_count = len(plant_problems)
                # Get device_id and user-overridden name from entity registry
                registry_entry = entity_reg.async_get(plant.entity_id)
                device_id = registry_entry.device_id if registry_entry else None
                # Prefer the registry name (set when user renames the entity)
                # over the config-entry name which doesn't update on rename.
                friendly_name = (
                    registry_entry.name or plant.name if registry_entry else plant.name
                )

                plants_with_problems.append(
                    {
                        "entity_id": plant.entity_id,
                        "friendly_name": friendly_name,
                        "problem_count": problem_count,
                        "device_id": device_id,
                    }
                )
                total_problems += problem_count

        return {
            ATTR_PLANTS_WITH_PROBLEMS: plants_with_problems,
            "total_problems": total_problems,
            "total_plants": total_plants,
        }
