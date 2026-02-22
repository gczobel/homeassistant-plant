# Problem Detection and Websocket Architecture

Reference documentation for how the plant integration detects problems and communicates with the frontend.

## Problem Detection System

### Overview

The plant entity (`PlantDevice`) monitors sensor values against configurable thresholds and reports an overall state of `"ok"`, `"problem"`, or `"unknown"`.

### File: `custom_components/plant/__init__.py`

#### Main Entity State

**Lines 988-1218: `update()` method**

The plant's state is calculated by checking each sensor type against its thresholds:

```python
def update(self) -> None:
    """Run on every update of the entities"""

    new_state = STATE_OK  # Start optimistic
    known_state = False

    # For each sensor type (moisture, conductivity, temperature, etc.)...
    if self.sensor_moisture is not None:
        moisture = getattr(self.hass.states.get(self.sensor_moisture.entity_id), "state", None)
        if moisture is not None and moisture != STATE_UNKNOWN and moisture != STATE_UNAVAILABLE:
            known_state = True
            self.moisture_status = self._check_threshold(
                float(moisture),
                self.min_moisture,
                self.max_moisture,
                self.moisture_status,
            )
            # If status is LOW or HIGH AND trigger is enabled → problem
            if (
                self.moisture_status in (STATE_LOW, STATE_HIGH)
                and self.moisture_trigger
            ):
                new_state = STATE_PROBLEM

    # ... repeat for all 8 sensor types ...

    if not known_state:
        new_state = STATE_UNKNOWN

    self._attr_state = new_state  # Set the entity state
    self.update_registry()
```

#### Hysteresis (Lines 967-986)

Prevents state flapping when sensor values hover near thresholds:

```python
def _check_threshold(self, value, min_entity, max_entity, current_status):
    """Check a value against min/max thresholds with hysteresis.

    Returns STATE_LOW, STATE_HIGH, or STATE_OK.
    When already in a problem state, require the value to cross back
    by a margin (hysteresis band) before clearing.
    """
    min_val = float(min_entity.state)
    max_val = float(max_entity.state)
    band = (max_val - min_val) * HYSTERESIS_FRACTION  # 10% of range

    if value < min_val:
        return STATE_LOW
    if value > max_val:
        return STATE_HIGH
    # Require crossing back by margin to clear
    if current_status == STATE_LOW and value <= min_val + band:
        return STATE_LOW
    if current_status == STATE_HIGH and value >= max_val - band:
        return STATE_HIGH
    return STATE_OK
```

#### Trigger Flags

Each sensor type has a boolean trigger flag that enables/disables problem detection:

- `self.moisture_trigger`
- `self.conductivity_trigger`
- `self.temperature_trigger`
- `self.humidity_trigger`
- `self.co2_trigger`
- `self.soil_temperature_trigger`
- `self.illuminance_trigger`
- `self.dli_trigger`

**If a sensor is out of range but its trigger is disabled, it won't cause a problem state.**

#### Special Cases

**Illuminance** (lines 1154-1191):
- Only checks `STATE_HIGH`, not `STATE_LOW` (would trigger every night)
- Skipped entirely if source provides PPFD (thresholds are in lux)

**DLI** (lines 1195-1210):
- Uses yesterday's full-day value, not instant reading
- Reads from `self.dli.extra_state_attributes["last_period"]`

### Individual Status Storage

Each sensor's status is stored as an instance variable:

```python
self.moisture_status       # STATE_LOW, STATE_HIGH, STATE_OK, or None
self.conductivity_status
self.temperature_status
self.humidity_status
self.co2_status
self.soil_temperature_status
self.illuminance_status
self.dli_status
```

These are exposed as entity attributes (see below).

### Aggregated Problems List

In addition to individual status fields, `update()` builds a `self._problems` list containing only the sensors that are actively causing problems (status is LOW/HIGH and trigger is enabled). Each entry is a dict:

```python
{
    "sensor_type": ATTR_MOISTURE,      # Which sensor
    "status": self.moisture_status,     # "Low" or "High"
    "current": str(moisture_val),       # Current reading
    "min": self.min_moisture.state,     # Min threshold
    "max": self.max_moisture.state,     # Max threshold
}
```

This list is exposed as the `problems` attribute on the plant entity (see Entity Attributes below).

---

## State Communication to Home Assistant

### How Problem State Reaches the Frontend

**1. External sensor changes** (e.g., `sensor.xiaomi_moisture: 45%`)

**2. Plant's meter sensor updates** (`custom_components/plant/sensor.py` line 418):
```python
self._attr_native_value = new_state.state  # Copy external sensor value
# Home Assistant's Entity base class auto-publishes state change
```

**3. Plant sensor state written to HA** → `sensor.my_plant_moisture: 45%` published to state machine

**4. Plant entity's `update()` called** → reads all sensor states, calculates problem status

**5. Plant state set** (line 1218):
```python
self._attr_state = new_state  # "ok" or "problem"
```

**6. Plant state automatically published** via Home Assistant's `Entity` framework

**7. Frontend receives update** via websocket connection (automatic, built into HA)

**8. Lovelace cards re-render** showing the problem indicator

---

## Entity Attributes (Lines 633-651)

The plant entity exposes detailed status in its attributes:

```python
@property
def extra_state_attributes(self) -> dict:
    """Return the device specific state attributes."""
    attributes = {
        ATTR_SPECIES: self.display_species,
        f"{ATTR_MOISTURE}_status": self.moisture_status,      # "low", "high", "ok", or None
        f"{ATTR_TEMPERATURE}_status": self.temperature_status,
        f"{ATTR_CONDUCTIVITY}_status": self.conductivity_status,
        f"{ATTR_ILLUMINANCE}_status": self.illuminance_status,
        f"{ATTR_HUMIDITY}_status": self.humidity_status,
        f"{ATTR_CO2}_status": self.co2_status,
        f"{ATTR_SOIL_TEMPERATURE}_status": self.soil_temperature_status,
        f"{ATTR_DLI}_status": self.dli_status,
        f"{ATTR_SPECIES}_original": self.species,
        ATTR_PROBLEMS: self._problems,           # [] or list of problem dicts
    }
    return attributes
```

**Example in Home Assistant:**

```yaml
plant.my_rose:
  state: "problem"
  attributes:
    species: "Rosa chinensis"
    moisture_status: "low"        # ← This sensor is too low
    temperature_status: "ok"
    conductivity_status: null     # Sensor unavailable/removed
    illuminance_status: "high"    # ← This sensor is too high
    humidity_status: "ok"
    co2_status: null
    soil_temperature_status: "ok"
    dli_status: "low"             # ← This sensor is too low
    problems:                      # ← Structured list of active problems
      - sensor_type: "moisture"
        status: "Low"
        current: "15.3"
        min: "20"
        max: "60"
      - sensor_type: "dli"
        status: "Low"
        current: "3.2"
        min: "5"
        max: "30"
```

Frontend cards can check these attributes to show **which** sensors caused the problem.
The `problems` attribute provides a machine-readable list usable in automations and templates.

---

## Custom Websocket API

### Purpose

Provides rich sensor data on-demand for Lovelace cards (like `lovelace-flower-card`).

### File: `custom_components/plant/__init__.py`

#### Registration (Line 292)

```python
websocket_api.async_register_command(hass, ws_get_info)
```

Called during integration setup to register the `plant/get_info` command.

#### Command Handler (Lines 424-453)

```python
@websocket_api.websocket_command({
    vol.Required("type"): "plant/get_info",
    vol.Required("entity_id"): str,
})
@callback
def ws_get_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Handle the websocket command."""
    # Find plant entity matching msg["entity_id"]
    plant_entity = hass.data[DOMAIN][key][ATTR_PLANT]
    if plant_entity.entity_id == msg["entity_id"]:
        connection.send_result(
            msg["id"], {"result": plant_entity.websocket_info}
        )
```

#### Usage from Frontend

JavaScript in browser (e.g., lovelace-flower-card):

```javascript
const result = await hass.callWS({
    type: "plant/get_info",
    entity_id: "plant.my_rose"
});

// result = { moisture: {...}, temperature: {...}, ... }
```

#### Response Format (Lines 704-778)

```python
@property
def websocket_info(self) -> dict:
    """Websocket response"""
    response = {}

    # For each sensor type...
    if self._sensor_available(self.sensor_moisture):
        response[ATTR_MOISTURE] = {
            ATTR_MAX: self.max_moisture.state,              # "60"
            ATTR_MIN: self.min_moisture.state,              # "20"
            ATTR_CURRENT: self.sensor_moisture.state,       # "45.3"
            ATTR_ICON: self._get_entity_icon(sensor),       # "mdi:water"
            ATTR_UNIT_OF_MEASUREMENT: sensor.unit_of_measurement,  # "%"
            ATTR_SENSOR: self.sensor_moisture.entity_id,    # "sensor.flower_moisture"
        }

    # ... repeat for temperature, conductivity, illuminance, humidity, CO2, soil_temp ...

    # DLI and DLI 24h have special handling

    return response
```

**Example Response:**

```json
{
  "moisture": {
    "max": "60",
    "min": "20",
    "current": "15.3",
    "icon": "mdi:water-percent",
    "unit_of_measurement": "%",
    "sensor": "sensor.flower_moisture"
  },
  "temperature": {
    "max": "30",
    "min": "15",
    "current": "22.5",
    "icon": "mdi:thermometer",
    "unit_of_measurement": "°C",
    "sensor": "sensor.flower_temperature"
  },
  "dli": {
    "max": "30.0",
    "min": "5.0",
    "current": 12.4,
    "icon": "mdi:weather-sunny",
    "unit_of_measurement": "mol/d⋅m²",
    "sensor": "sensor.my_rose_daily_light_integral"
  }
}
```

Only includes sensors that are available (have valid states).

---

## Global Problem Binary Sensor

### File: `custom_components/plant/binary_sensor.py`

A single `binary_sensor.plant_problems` entity that reports whether **any** plant has problems.

- **Registration:** Domain-level via `discovery.async_load_platform` in `async_setup` (same pattern as the core Energy integration and Adaptive Lighting for entities not owned by any config entry)
- **State:** `on` when any plant has `STATE_PROBLEM`, `off` otherwise
- **Update trigger:** Listens for state changes on plant entities via `async_track_state_change_event`. The listener is rebuilt dynamically (`_refresh_tracked_plants`) whenever a plant is added or removed, so plants created after startup are also tracked.
- **Attributes:** `plants_with_problems` (list), `total_problems`, `total_plants`

The sensor reference is stored at `hass.data[DOMAIN][DATA_GLOBAL_PROBLEM_SENSOR]`. All iterations over `hass.data[DOMAIN]` use `isinstance(entry_data, dict)` checks to skip this non-entry key.

**Unloading caveat:** Entities loaded via `discovery.async_load_platform` do not support unloading — the binary sensor persists until HA restarts even if all plant config entries are removed. This is an inherent limitation of domain-level entities, shared by the core Energy integration.

---

## Why Both Attributes AND Websocket?

### Entity Attributes
- **Push-based** — automatically sent with every state update
- **Simple access** — available in all entity contexts
- **Lightweight** — just the status ("low", "high", "ok")
- Use case: Quick check if problem exists and which sensors

### Websocket API
- **Pull-based** — card requests data only when needed
- **Rich data** — current values, thresholds, icons, units, entity IDs
- **Custom format** — optimized for card rendering
- Use case: Build detailed UI showing all sensor values and thresholds

---

## Data Flow Summary

```
External Sensor
    ↓
Plant Meter Sensor (copies value, publishes state)
    ↓
Plant Entity update() (reads all sensors, calculates problem, builds problems list)
    ↓
Plant State + Attributes incl. problems[] (published to HA state machine)
    ├──→ Global binary_sensor.plant_problems updates (listens to plant.* state changes)
    ↓
Frontend Websocket (automatic push from HA)
    ↓
Lovelace Card (shows problem indicator)
    ↓
(Optional) Card calls plant/get_info websocket (pull detailed data)
    ↓
Card renders detailed sensor info
```

---

## Key Constants

**States:**
- `STATE_OK = "ok"` — all sensors within range
- `STATE_PROBLEM = "problem"` — one or more sensors out of range (with trigger enabled)
- `STATE_UNKNOWN = "unknown"` — no sensor data available
- `STATE_LOW = "low"` — sensor below minimum threshold
- `STATE_HIGH = "high"` — sensor above maximum threshold

**Hysteresis:**
- `HYSTERESIS_FRACTION = 0.10` — 10% margin to clear problem state

**Attributes:**
- `ATTR_MOISTURE = "moisture"`
- `ATTR_TEMPERATURE = "temperature"`
- `ATTR_CONDUCTIVITY = "conductivity"`
- `ATTR_ILLUMINANCE = "illuminance"`
- `ATTR_HUMIDITY = "humidity"`
- `ATTR_CO2 = "co2"`
- `ATTR_SOIL_TEMPERATURE = "soil_temperature"`
- `ATTR_DLI = "dli"`
- `ATTR_MAX = "max"`
- `ATTR_MIN = "min"`
- `ATTR_CURRENT = "current"`
- `ATTR_PROBLEMS = "problems"`
- `ATTR_PLANTS_WITH_PROBLEMS = "plants_with_problems"`

---

## Related Files

- `custom_components/plant/__init__.py` — PlantDevice entity, update() method, websocket API, global sensor registration
- `custom_components/plant/binary_sensor.py` — Global PlantMonitorProblemSensor (domain-level)
- `custom_components/plant/sensor.py` — PlantCurrentStatus meter sensors, state tracking
- `custom_components/plant/const.py` — Constants
- `https://github.com/Olen/lovelace-flower-card` — Frontend card that uses this API

---

Generated: 2026-02-16
Updated: 2026-02-18 — Added problems attribute, global binary sensor
