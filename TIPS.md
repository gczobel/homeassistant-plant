# 💡 Tips & Tricks

Practical tips, template examples, and workarounds for common situations with the Plant Monitor integration.

---

## 📑 Table of Contents

- [💡 Tips & Tricks](#-tips--tricks)
  - [🔧 Fixing Sensors with Wrong or Missing Device Class](#-fixing-sensors-with-wrong-or-missing-device-class)
  - [💧 Auto-Watering with Averaged Moisture](#-auto-watering-with-averaged-moisture)
  - [🚨 Problem Notification Automation](#-problem-notification-automation)
  - [📋 Problem Dashboard Card](#-problem-dashboard-card)
  - [🌤️ Weather Forecast Warnings for Outdoor Plants](#️-weather-forecast-warnings-for-outdoor-plants)
  - [🌡️ Combining Multiple Temperature Sources](#️-combining-multiple-temperature-sources)
  - [📊 Export Plant Config as YAML](#-export-plant-config-as-yaml)

---

## 🔧 Fixing Sensors with Wrong or Missing Device Class

This is the most common issue users run into. The sensor dropdowns in the config flow filter by `device_class`, and many integrations (especially Zigbee and BLE sensors) don't set it correctly. A humidity sensor might report soil moisture, or a soil sensor might have no `device_class` at all.

There are three ways to work around this:

### Option 1: Use `customize.yaml` *(simplest)*

Override the device class directly in your HA configuration. No new entities created.

```yaml
# In customize.yaml
sensor.my_zigbee_soil_sensor:
  device_class: moisture

sensor.my_humidity_sensor_used_for_soil:
  device_class: moisture
```

Restart Home Assistant after editing. The sensor will now appear in the correct dropdown.

### Option 2: Create a Template Sensor

Create a new sensor with the correct `device_class`. Useful when you also want to rename the sensor or add processing.

```yaml
# In configuration.yaml (or a templates/ file)
template:
  - sensor:
      - name: "Garden Soil Moisture"
        unique_id: "garden_soil_moisture_fixed"
        state: "{{ states('sensor.zigbee_soil_sensor_humidity') }}"
        unit_of_measurement: "%"
        device_class: moisture
        state_class: measurement
```

### Option 3: Use `replace_sensor` After Setup

The `plant.replace_sensor` action has **more relaxed** validation than the setup flow and the **Configure** → **Replace sensors** UI — it does not filter by `device_class`, so it accepts any `sensor.*` entity. You can:

1. Set up the plant **without** the problematic sensor
2. Use **Developer Tools** → **Actions** → `plant.replace_sensor` to assign it

```yaml
action: plant.replace_sensor
data:
  meter_entity: sensor.my_plant_soil_moisture
  new_sensor: sensor.zigbee_sensor_with_wrong_device_class
```

> [!NOTE]
> If the plant sensor entity is disabled (because no source was configured during setup), you must **enable** it first on the device page before it appears in the entity picker. See [Adding a sensor to an existing plant](README.md#adding-a-sensor-to-an-existing-plant).

### Which Option to Choose?

| Option | Pros | Cons |
|--------|------|------|
| `customize.yaml` | Simple, no extra entities | Affects the sensor globally |
| Template sensor | Full control, can rename/process | Extra entity to maintain |
| `replace_sensor` | No config changes needed, available from UI | Sensor must be enabled first |

> [!TIP]
> Regardless of the workaround, **report the missing `device_class` to the integration that owns the physical sensor**. That's the only way to fix it permanently for everyone.

---

## 💧 Auto-Watering with Averaged Moisture

If you have an auto-watering system serving multiple plants, you probably don't want it to trigger just because one plant is slightly dry. This template sensor averages the soil moisture across all plants in an area:

```yaml
template:
  - sensor:
      - name: "Average Soil Moisture Outside"
        unique_id: "average_soil_moisture_outside"
        unit_of_measurement: "%"
        device_class: moisture
        state_class: measurement
        state: >
          {%- set ns = namespace(total=0, count=0) -%}
          {%- for device_id in area_devices("outside") -%}
            {%- for entity_id in device_entities(device_id) -%}
              {%- if entity_id.startswith("sensor.") and "moisture" in entity_id -%}
                {%- set val = states(entity_id) | float(default=-1) -%}
                {%- if val >= 0 -%}
                  {%- set ns.total = ns.total + val -%}
                  {%- set ns.count = ns.count + 1 -%}
                {%- endif -%}
              {%- endfor -%}
            {%- endfor -%}
          {%- endfor -%}
          {{ (ns.total / ns.count) | round(1) if ns.count > 0 else 0 }}
```

This updates automatically when plants are added to or removed from the area.

You can then use this as a trigger for your watering automation:

```yaml
automation:
  - alias: "Water outdoor plants"
    trigger:
      - platform: numeric_state
        entity_id: sensor.average_soil_moisture_outside
        below: 30
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.garden_irrigation
```

---

## 🚨 Problem Notification Automation

> [!TIP]
> The integration includes built-in [hysteresis](README.md#hysteresis) on all thresholds, so plants won't flap between OK and PROBLEM when a sensor value hovers near a boundary. This significantly reduces duplicate notifications without any extra configuration.

Get notified when any plant has a problem:

```yaml
automation:
  - alias: "Plant problem notification"
    trigger:
      - platform: state
        entity_id:
          - plant.rose
          - plant.tomato
          - plant.basil
        to: "problem"
    action:
      - service: notify.mobile_app
        data:
          title: "🌱 Plant needs attention"
          message: >
            {{ trigger.to_state.attributes.friendly_name }} has a problem!
```

To include which specific sensor triggered the issue, check the plant's attributes:

```yaml
          message: >
            {{ trigger.to_state.attributes.friendly_name }} has a problem.
            {% for attr in ['moisture_status', 'temperature_status', 'conductivity_status', 'illuminance_status', 'humidity_status', 'dli_status'] %}
              {% if trigger.to_state.attributes.get(attr) in ['Low', 'High'] %}
              - {{ attr | replace('_status', '') | title }}: {{ trigger.to_state.attributes[attr] }}
              {% endif %}
            {% endfor %}
```

---

## 📋 Problem Dashboard Card

A Lovelace card that displays all plants with active problems, including visual progress bars showing where each sensor value falls relative to its thresholds. It uses `binary_sensor.plant_problems` and the per-plant `problems` attribute.

<!-- TODO: add screenshot -->

> [!NOTE]
> This card requires [custom:html-template-card](https://github.com/PiotrMachworski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card) installed via HACS.

```yaml
type: grid
cards:
  - type: heading
    heading_style: title
    heading: Plant Problems
  - type: custom:html-template-card
    ignore_line_breaks: true
    content: >
      {% set plants = state_attr('binary_sensor.plant_problems',
      'plants_with_problems') %}

      {% if not plants %}
        <div style="color:var(--secondary-text-color); text-align:center; padding:16px;">All plants are healthy.</div>
      {% else %}
        {% for plant_info in plants %}
          {% set problems = state_attr(plant_info.entity_id, 'problems') %}
          <div style="padding:10px 0; border-bottom:1px solid var(--divider-color);">
            <a href="/config/devices/device/{{ plant_info.device_id }}"
               style="display:block; font-size:16px; font-weight:bold; text-decoration:none; color:var(--primary-text-color); margin-bottom:8px;">
              {{ plant_info.friendly_name }}
              <span style="font-size:12px; color:var(--secondary-text-color); font-weight:normal;">
                — {{ plant_info.problem_count }} problem{{ 's' if plant_info.problem_count != 1 }}
              </span>
            </a>
            {% if problems %}
              {% for p in problems %}
                {% set min_val = p.min | float %}
                {% set max_val = p.max | float %}
                {% set cur_val = p.current | float %}
                {% set range   = max_val - min_val %}
                {% set is_low  = p.status == 'Low' %}
                {% set color   = 'var(--error-color, crimson)' %}
                {% set icons = {
                  'Moisture':         'mdi:water',
                  'temperature':      'mdi:thermometer',
                  'conductivity':     'mdi:spa-outline',
                  'illuminance':      'mdi:brightness-6',
                  'humidity':         'mdi:water-percent',
                  'soil_temperature': 'mdi:thermometer-probe',
                  'dli':              'mdi:counter',
                  'co2':              'mdi:molecule-co2'
                } %}
                {% set icon = icons.get(p.sensor_type, 'mdi:leaf') %}
                {% set seg1_pct = 100 %}
                {% set seg2_pct = 0 if is_low else 100 %}
                {% set seg3_pct = 0 if is_low else 100 %}

                <div style="margin:6px 0 14px 0;">
                  <div style="display:flex; align-items:center; justify-content:space-between; font-size:12px; margin-bottom:15px;">
                    <div style="display:flex; align-items:center; gap:15px;">
                      <ha-icon icon="{{ icon }}" style="width:16px; height:16px;"></ha-icon>
                      <span>{{ p.sensor_type | replace('_', ' ') | title }}</span>
                    </div>
                    <span style="color:{{ color }}; font-weight:bold;">{{ p.status }} · {{ p.current }}</span>
                  </div>
                  <div style="display:flex; gap:3px; width:100%;">
                    <div style="flex:1; height:8px; background:var(--primary-background-color); border-radius:2px; overflow:hidden;">
                      <div style="height:100%; width:{{ seg1_pct }}%;
                                  background:{{ color if is_low else 'var(--success-color, mediumseagreen)' }};"></div>
                    </div>
                    <div style="flex:10; height:8px; background:var(--primary-background-color); border-radius:2px; overflow:hidden;">
                      <div style="height:100%; width:{{ seg2_pct }}%; background:var(--success-color, mediumseagreen);"></div>
                    </div>
                    <div style="flex:1; height:8px; background:var(--primary-background-color); border-radius:2px; overflow:hidden;">
                      <div style="height:100%; width:{{ seg3_pct }}%;
                                  background:{{ color if not is_low else 'transparent' }};"></div>
                    </div>
                  </div>
                  <div style="display:flex; justify-content:space-between; font-size:10px; color:var(--secondary-text-color); margin-top:3px;">
                    <span>{{ p.min }}</span><span>{{ p.max }}</span>
                  </div>
                </div>
              {% endfor %}
            {% endif %}
          </div>
        {% endfor %}
      {% endif %}
```

---

## 🌤️ Weather Forecast Warnings for Outdoor Plants

Get warned the evening before when tomorrow's forecast shows temperatures outside your outdoor plants' configured thresholds — giving you time to move them indoors or cover them.

This automation combines two things you already have: your weather integration's forecast and the per-plant threshold entities created by Plant Monitor (`number.<plant>_min_temperature`, etc.).

```yaml
automation:
  - alias: "Plant weather warning"
    description: >
      Compares tomorrow's weather forecast against outdoor plants'
      temperature thresholds. Notifies if any plant may be at risk.

    trigger:
      # ── When to check ─────────────────────────────────────────
      # Evening gives you time to act before overnight lows.
      # Adjust the time to fit your routine.
      - platform: time
        at: "18:00:00"

    action:
      # ── Step 1: Fetch the daily forecast ───────────────────────
      # Replace "weather.home" with your weather entity.
      # You can test what your integration returns in
      # Developer Tools → Actions → weather.get_forecasts.
      - action: weather.get_forecasts
        target:
          entity_id: weather.home
        data:
          type: daily
        response_variable: forecast

      # ── Step 2: Extract tomorrow's temperatures ────────────────
      - variables:
          # Daily forecasts typically list today as [0] and tomorrow
          # as [1]. Check the "datetime" field in the response from
          # Developer Tools to verify this for your weather integration.
          tomorrow: "{{ forecast['weather.home'].forecast[1] }}"
          forecast_high: "{{ tomorrow.temperature | float }}"
          forecast_low: "{{ tomorrow.templow | float }}"

          # ── Your outdoor plants ────────────────────────────────
          # List only plants that are actually outdoors. Indoor
          # plants aren't affected by weather and don't need this.
          outdoor_plants:
            - plant.rose
            - plant.tomato
            - plant.basil

          # ── Step 3: Check each plant's thresholds ──────────────
          # For each plant, we look up its min/max temperature
          # threshold entities. These follow the naming pattern:
          #
          #   number.<plant_slug>_max_temperature
          #   number.<plant_slug>_min_temperature
          #
          # where <plant_slug> is the part after "plant." in the
          # entity ID (e.g. plant.rose → number.rose_min_temperature).
          #
          # The default values (-999 / 999) ensure that a missing
          # threshold entity never triggers a false warning.
          warnings: >
            {% set ns = namespace(items=[]) %}
            {% for plant_id in outdoor_plants %}
              {% set name = state_attr(plant_id, 'friendly_name') %}
              {% set slug = plant_id | replace('plant.', '') %}
              {% set min_t = states('number.' ~ slug ~ '_min_temperature') | float(-999) %}
              {% set max_t = states('number.' ~ slug ~ '_max_temperature') | float(999) %}
              {% if forecast_low < min_t %}
                {% set ns.items = ns.items + [
                  name ~ ' — forecast low ' ~ forecast_low ~ '° is below min threshold ' ~ min_t ~ '°'
                ] %}
              {% endif %}
              {% if forecast_high > max_t %}
                {% set ns.items = ns.items + [
                  name ~ ' — forecast high ' ~ forecast_high ~ '° exceeds max threshold ' ~ max_t ~ '°'
                ] %}
              {% endif %}
            {% endfor %}
            {{ ns.items }}

      # ── Step 4: Only notify when there's something to report ───
      - condition: template
        value_template: "{{ warnings | length > 0 }}"

      # ── Step 5: Send the notification ──────────────────────────
      # Replace with your preferred notify service.
      - action: notify.mobile_app
        data:
          title: "Plant weather warning"
          message: >
            Tomorrow's forecast ({{ forecast_low }}°–{{ forecast_high }}°)
            may affect these plants:
            {% for w in warnings %}
            - {{ w }}
            {% endfor %}
```

### Customizing

**Use an area instead of a manual list.** If all your outdoor plants are in the same area, replace the `outdoor_plants` variable with:

```yaml
          outdoor_plants: >
            {{ area_entities("garden") | select("match", "^plant\\.") | list }}
```

This picks up new plants automatically when they're added to the area.

**Add humidity checks.** If your weather integration includes humidity in its daily forecast, extend the comparison inside the `{% for plant_id ... %}` loop:

```yaml
              {% set min_h = states('number.' ~ slug ~ '_min_humidity') | float(-999) %}
              {% set max_h = states('number.' ~ slug ~ '_max_humidity') | float(999) %}
              {% if tomorrow.humidity is defined %}
                {% if tomorrow.humidity | float < min_h %}
                  {% set ns.items = ns.items + [name ~ ' — humidity ' ~ tomorrow.humidity ~ '% below min ' ~ min_h ~ '%'] %}
                {% endif %}
                {% if tomorrow.humidity | float > max_h %}
                  {% set ns.items = ns.items + [name ~ ' — humidity ' ~ tomorrow.humidity ~ '% above max ' ~ max_h ~ '%'] %}
                {% endif %}
              {% endif %}
```

> [!NOTE]
> Not all weather integrations include humidity in their daily forecast. Check what fields your integration provides in **Developer Tools** → **Actions** → `weather.get_forecasts`.

---

## 🌡️ Combining Multiple Temperature Sources

If you have multiple temperature sensors near a plant and want to use the average:

```yaml
template:
  - sensor:
      - name: "Greenhouse Average Temperature"
        unique_id: "greenhouse_avg_temp"
        unit_of_measurement: "°C"
        device_class: temperature
        state_class: measurement
        state: >
          {% set sensors = [
            states('sensor.greenhouse_temp_1') | float(0),
            states('sensor.greenhouse_temp_2') | float(0)
          ] %}
          {% set valid = sensors | select('greaterthan', -40) | list %}
          {{ (valid | sum / valid | count) | round(1) if valid else 'unavailable' }}
```

---

## 📊 Export Plant Config as YAML

This template generates YAML config from your current UI-configured plants. Useful for backup or migration purposes.

Modify the area names to match your setup:

```jinja2
{% set device_ids = area_devices("living_room") + area_devices("garden") %}
{% set ns = namespace(is_plant=False) %}
{%- for device_id in device_ids %}
  {%- set ns.is_plant = False %}
  {%- for entity_id in device_entities(device_id) -%}
    {%- if entity_id.startswith("plant.") %}
    {%- set ns.is_plant = True %}
{{ entity_id.replace(".", "_") }}:
  species: {{ state_attr(entity_id, "species_original") }}
  name: {{ state_attr(entity_id, "friendly_name") }}
  image: {{ state_attr(entity_id, "entity_picture") }}
  sensors:
    {%- endif %}
  {%- endfor %}
  {%- if ns.is_plant == True %}
    {%- for entity_id in device_entities(device_id) -%}
      {%- if entity_id.startswith("sensor.") and state_attr(entity_id, "external_sensor") %}
        {%- if "illuminance" in entity_id %}
    brightness: {{ state_attr(entity_id, "external_sensor") }}
        {%- endif %}
        {%- if "conduct" in entity_id %}
    conductivity: {{ state_attr(entity_id, "external_sensor") }}
        {%- endif %}
        {%- if "moist" in entity_id %}
    moisture: {{ state_attr(entity_id, "external_sensor") }}
        {%- endif %}
        {%- if "temp" in entity_id %}
    temperature: {{ state_attr(entity_id, "external_sensor") }}
        {%- endif %}
      {%- endif %}
    {%- endfor %}
  {%- endif %}
{%- endfor %}
```

Use this in **Developer Tools** → **Template** to generate the output.
