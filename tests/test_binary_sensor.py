"""Tests for the global plant problem binary sensor."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, STATE_PROBLEM
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plant.const import ATTR_PLANT, DOMAIN

from .common import set_external_sensor_states, update_plant_sensors


class TestGlobalProblemSensor:
    """Tests for binary_sensor.plant_problems."""

    async def test_global_sensor_created(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that the global problem sensor is created during setup."""
        # Check that the sensor exists in hass.data
        assert "global_problem_sensor" in hass.data[DOMAIN]

        # Check that the entity exists
        state = hass.states.get("binary_sensor.plant_problems")
        assert state is not None
        assert state.state == STATE_OFF  # No problems initially

    async def test_sensor_off_when_no_problems(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test sensor is off when all plants are healthy."""
        # Set all sensors to healthy values
        await set_external_sensor_states(
            hass,
            moisture=50,
            temperature=22,
            conductivity=1000,
            illuminance=5000,
        )
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.plant_problems")
        assert state.state == STATE_OFF
        assert state.attributes["total_problems"] == 0
        assert state.attributes["total_plants"] == 1
        assert state.attributes["plants_with_problems"] == []

    async def test_sensor_on_when_plant_has_problem(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test sensor is on when a plant has a problem."""
        # Set moisture too low (min is 20)
        await set_external_sensor_states(
            hass,
            moisture=10,
            temperature=22,
            conductivity=1000,
            illuminance=5000,
        )
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        # Verify plant has problem state
        plant = hass.data[DOMAIN][init_integration.entry_id][ATTR_PLANT]
        assert plant._attr_state == STATE_PROBLEM

        # Verify global sensor is on
        state = hass.states.get("binary_sensor.plant_problems")
        assert state.state == STATE_ON

    async def test_attributes_include_friendly_name_and_device_id(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that plants_with_problems includes friendly_name and device_id."""
        # Set moisture too low to trigger problem
        await set_external_sensor_states(
            hass,
            moisture=10,
            temperature=22,
            conductivity=1000,
            illuminance=5000,
        )
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.plant_problems")
        plants_with_problems = state.attributes["plants_with_problems"]

        assert len(plants_with_problems) == 1
        plant_info = plants_with_problems[0]

        # Check all expected fields are present
        assert "entity_id" in plant_info
        assert "friendly_name" in plant_info
        assert "problem_count" in plant_info
        assert "device_id" in plant_info

        # Verify friendly_name matches the plant name
        plant = hass.data[DOMAIN][init_integration.entry_id][ATTR_PLANT]
        assert plant_info["friendly_name"] == plant.name

        # Verify device_id is valid
        entity_reg = er.async_get(hass)
        registry_entry = entity_reg.async_get(plant_info["entity_id"])
        assert plant_info["device_id"] == registry_entry.device_id

    async def test_problem_count_matches_problems_list(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that problem_count matches the number of problems in the plant's problems attribute."""
        # Set multiple sensors out of range
        await set_external_sensor_states(
            hass,
            moisture=10,  # Too low (min: 20)
            temperature=35,  # Too high (max: 40, but we need it higher than default max 32)
            conductivity=1000,
            illuminance=5000,
        )
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.plant_problems")
        plants_with_problems = state.attributes["plants_with_problems"]

        assert len(plants_with_problems) == 1
        plant_info = plants_with_problems[0]

        # Get the plant's problems from the plant entity directly
        plant = hass.data[DOMAIN][init_integration.entry_id][ATTR_PLANT]
        plant_problems = plant._problems

        # problem_count should match the length of the problems list
        assert plant_info["problem_count"] == len(plant_problems)
        # Only moisture should be a problem (temp is 35 but max is 40)
        assert plant_info["problem_count"] == 1

    async def test_total_problems_aggregated(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that total_problems is the sum of all problems across plants."""
        # Set multiple sensors out of range
        await set_external_sensor_states(
            hass,
            moisture=10,  # Too low (min: 20)
            temperature=45,  # Too high (max: 40)
            conductivity=1000,
            illuminance=5000,
        )
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.plant_problems")
        assert state.attributes["total_problems"] == 2
        assert state.attributes["total_plants"] == 1
