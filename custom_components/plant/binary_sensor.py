"""Global problem binary sensor for the plant integration.

Registered at domain level (like the ws_get_info websocket API) rather than
per-entry, since this is a single global sensor not tied to any specific plant.
"""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import STATE_PROBLEM
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import ATTR_PLANT, ATTR_PLANTS_WITH_PROBLEMS, DOMAIN

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
    hass.data[DOMAIN]["global_problem_sensor"] = sensor


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

    async def async_added_to_hass(self) -> None:
        """Register state change listener when added to hass."""

        @callback
        def _plant_state_changed(event: Event) -> None:
            """Handle plant state changes."""
            if event.data.get("entity_id", "").startswith("plant."):
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [
                    entry_data[ATTR_PLANT].entity_id
                    for entry_data in self.hass.data.get(DOMAIN, {}).values()
                    if isinstance(entry_data, dict) and ATTR_PLANT in entry_data
                ],
                _plant_state_changed,
            )
        )

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
                plants_with_problems.append(
                    {
                        "entity_id": plant.entity_id,
                        "problem_count": problem_count,
                    }
                )
                total_problems += problem_count

        return {
            ATTR_PLANTS_WITH_PROBLEMS: plants_with_problems,
            "total_problems": total_problems,
            "total_plants": total_plants,
        }
