"""Tests for the global plant problem binary sensor."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, STATE_PROBLEM
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plant.binary_sensor import PlantMonitorProblemSensor
from custom_components.plant.const import ATTR_PLANT, DATA_GLOBAL_PROBLEM_SENSOR, DOMAIN

from .common import set_external_sensor_states, update_plant_sensors


class TestGlobalProblemSensor:
    """Tests for binary_sensor.plant_problems."""

    async def test_global_sensor_created(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that the global problem sensor is created during setup."""
        # Check that the sensor exists in hass.data via the constant key
        assert DATA_GLOBAL_PROBLEM_SENSOR in hass.data[DOMAIN]
        assert isinstance(
            hass.data[DOMAIN][DATA_GLOBAL_PROBLEM_SENSOR],
            PlantMonitorProblemSensor,
        )

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

    async def test_sensor_recovers_to_off(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test global sensor returns to off after plant recovers from problem."""
        # First cause a problem
        await set_external_sensor_states(
            hass,
            moisture=10,  # Too low
            temperature=22,
            conductivity=1000,
            illuminance=5000,
        )
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.plant_problems")
        assert state.state == STATE_ON

        # Now fix the problem (value must clear hysteresis band: min=20, band=2.0)
        await set_external_sensor_states(hass, moisture=50)
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.plant_problems")
        assert state.state == STATE_OFF
        assert state.attributes["total_problems"] == 0

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

        # Verify friendly_name matches the plant name (no rename yet)
        plant = hass.data[DOMAIN][init_integration.entry_id][ATTR_PLANT]
        assert plant_info["friendly_name"] == plant.name

        # Verify device_id is valid
        entity_reg = er.async_get(hass)
        registry_entry = entity_reg.async_get(plant_info["entity_id"])
        assert plant_info["device_id"] == registry_entry.device_id

    async def test_friendly_name_updates_after_rename(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that friendly_name reflects entity registry rename, not config entry."""
        # Trigger a problem so the plant appears in plants_with_problems
        await set_external_sensor_states(
            hass,
            moisture=10,
            temperature=22,
            conductivity=1000,
            illuminance=5000,
        )
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        plant = hass.data[DOMAIN][init_integration.entry_id][ATTR_PLANT]
        entity_reg = er.async_get(hass)

        # Rename the entity via the registry (same as UI rename)
        entity_reg.async_update_entity(plant.entity_id, name="Renamed Plant")
        await hass.async_block_till_done()

        # Re-trigger state update so the global sensor recalculates attributes
        await update_plant_sensors(hass, init_integration.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.plant_problems")
        plants_with_problems = state.attributes["plants_with_problems"]
        assert len(plants_with_problems) == 1
        assert plants_with_problems[0]["friendly_name"] == "Renamed Plant"

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


class TestDynamicPlantTracking:
    """Tests for _refresh_tracked_plants — tracking plants added/removed after startup.

    The global sensor registers state-change listeners for all plant entities.
    Without dynamic refresh, plants added after the sensor's initial setup
    would not trigger updates. These tests verify the refresh mechanism.
    """

    async def test_initial_plant_is_tracked(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that a plant present at startup is tracked by the global sensor."""
        global_sensor = hass.data[DOMAIN][DATA_GLOBAL_PROBLEM_SENSOR]
        plant = hass.data[DOMAIN][init_integration.entry_id][ATTR_PLANT]

        assert plant.entity_id in global_sensor._tracked_entity_ids

    async def test_refresh_is_noop_when_unchanged(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that _refresh_tracked_plants does nothing when plant set is unchanged."""
        global_sensor = hass.data[DOMAIN][DATA_GLOBAL_PROBLEM_SENSOR]
        old_listener = global_sensor._remove_listener

        # Call refresh again — should be a no-op
        global_sensor._refresh_tracked_plants()

        assert global_sensor._remove_listener is old_listener

    async def test_removed_plant_is_untracked(
        self,
        hass: HomeAssistant,
        init_integration: MockConfigEntry,
    ) -> None:
        """Test that removing a plant updates the tracked set."""
        global_sensor = hass.data[DOMAIN][DATA_GLOBAL_PROBLEM_SENSOR]
        plant = hass.data[DOMAIN][init_integration.entry_id][ATTR_PLANT]

        assert plant.entity_id in global_sensor._tracked_entity_ids

        # Simulate removing the plant entry from hass.data and refreshing
        # (mimics what async_unload_entry does before calling _refresh)
        saved_entry_data = hass.data[DOMAIN].pop(init_integration.entry_id, None)
        global_sensor._refresh_tracked_plants()

        assert global_sensor._tracked_entity_ids == set()
        assert global_sensor._remove_listener is None

        # Restore so the init_integration fixture teardown can unload cleanly
        hass.data[DOMAIN][init_integration.entry_id] = saved_entry_data
