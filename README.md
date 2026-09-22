# Sol-Ark Cloud for Home Assistant

Monitor a Sol-Ark plant in Home Assistant with support for gateways, multiple
inverters, batteries, and the Home Assistant Energy Dashboard.

## Features

- Whole-site solar, load, grid, battery, generator, and Smart Load monitoring
- Separate grid import/export and battery charge/discharge sensors
- Energy Dashboard-ready kWh entities—no manual helpers required
- Automatic discovery of gateways and parallel inverters
- Device details including model, serial number, firmware, and connection status
- Automatic API discovery and credential reauthentication
- Downloadable, privacy-safe diagnostics

## Installation

### HACS

1. Open **HACS → Integrations**.
2. Select **Custom repositories** from the menu.
3. Add `https://github.com/HammondAutomationHub/HomeAssistant_SolArk` as an
   **Integration**.
4. Install **SolArk Cloud** and restart Home Assistant.
5. Open **Settings → Devices & services → Add integration** and select
   **SolArk Cloud**.

### Manual installation

Copy `custom_components/solark` into the `custom_components` directory in your Home
Assistant configuration, restart Home Assistant, and add **SolArk Cloud** from
**Settings → Devices & services**.

## Configuration

You will need:

- Your Sol-Ark Cloud username and password
- Your plant ID

To find the plant ID, sign in at [Sol-Ark Cloud](https://www.solarkcloud.com), open
your plant, and look for the number in its overview URL.

Keep **Automatically discover API URL** enabled unless you have a specific reason to
override it. The default polling interval is 30 seconds.

## Devices

The integration organizes equipment into separate Home Assistant devices:

```text
Sol-Ark Plant
  Gateway / data logger
    Inverter
      Battery information, when available
```

Parallel installations show each inverter separately while retaining a whole-site
plant device. Use plant entities for dashboards and automations representing the
entire installation. Inverter and gateway entities are intended for equipment
monitoring and troubleshooting.

### Parallel-inverter aggregation

Sol-Ark Cloud does not give consistent plant PV totals for every parallel system.
The integration calculates whole-site PV power, PV energy today, and PV lifetime
energy by summing the corresponding value from every discovered physical inverter.
The site value is unavailable unless every expected inverter contributes; it is never
silently calculated from only part of the system. These entities expose
`contributing_inverters`, `expected_inverters`, and `aggregation_method` attributes.

Load, grid, and battery power use the plant flow endpoint. It supplies site-level
values and direction flags (grid import/export and battery charge/discharge), while
summing inverter copies could double-count firmware that repeats a master/system
value. Their aggregate entities identify the method as `authoritative_site_flow`.
PV/load/grid/battery power entities also include an `energy_balance` attribute with
source power, sink power, and instantaneous balance error. A large error diagnoses
incomplete or inconsistent cloud telemetry; it is not an Energy Dashboard correction.
If the inverter-list endpoint has never exposed a physical inverter since startup,
the integration cannot infer that device. Diagnostics will show the discovered
`expected_inverters` count; this remains a Sol-Ark Cloud API limitation.

## Main plant sensors

| Entity | Unit | Description |
|---|---:|---|
| `sensor.solark_pv_power` | W | Total solar production |
| `sensor.solark_load_power` | W | Total site consumption |
| `sensor.solark_grid_power` | W | Positive import, negative export |
| `sensor.solark_grid_import_power` | W | Power imported from the grid |
| `sensor.solark_grid_export_power` | W | Power exported to the grid |
| `sensor.solark_battery_power` | W | Positive discharge, negative charge |
| `sensor.solark_battery_charge_power` | W | Battery charging power |
| `sensor.solark_battery_discharge_power` | W | Battery discharging power |
| `sensor.solark_battery_soc` | % | Battery state of charge |
| `sensor.solark_generator_power` | W | Generator power, when available |
| `sensor.solark_smart_load_power` | W | Smart Load power, when available |
| `sensor.solark_energy_today` | kWh | Solar energy produced today |
| `sensor.solark_energy_total` | kWh | Total solar energy produced |
| `sensor.solark_grid_import_energy` | kWh | Total grid energy imported |
| `sensor.solark_grid_export_energy` | kWh | Total grid energy exported |
| `sensor.solark_battery_charge_energy` | kWh | Total energy charged into the battery |
| `sensor.solark_battery_discharge_energy` | kWh | Total energy discharged from the battery |
| `sensor.solark_load_energy` | kWh | Total site energy consumption |
| `sensor.solark_load_energy_today` | kWh | Site energy consumption today |

Open an equipment device in Home Assistant to see the sensors available for that
inverter, battery, gateway, and firmware. Equipment diagnostics expose all known
values returned by the normalized API catalogue, including per-phase grid/output/load
measurements, PV-string measurements, native daily and lifetime energy counters,
battery limits and temperatures, generator measurements, connectivity, and operating
flags. Unsupported values remain unavailable rather than reporting zero.

## Energy Dashboard setup

No Riemann-sum helpers or template sensors are required.

Open **Settings → Dashboards → Energy** and select the following entities from the
Sol-Ark plant device:

| Energy Dashboard section | Field | Entity |
|---|---|---|
| Solar panels | Solar production energy | `sensor.solark_energy_total` |
| Solar panels | Solar production power | `sensor.solark_pv_power` |
| Electricity grid | Energy consumed from the grid | `sensor.solark_grid_import_energy` |
| Electricity grid | Energy returned to the grid | `sensor.solark_grid_export_energy` |
| Home battery storage | Energy going in to the battery | `sensor.solark_battery_charge_energy` |
| Home battery storage | Energy coming out of the battery | `sensor.solark_battery_discharge_energy` |

The display name is optional and can be left unchanged.

For the battery's **Type of power measurement**, select **Two Sensors**. Set
`sensor.solark_battery_charge_power` as the charging power sensor and
`sensor.solark_battery_discharge_power` as the discharging power sensor. Select
`sensor.solark_battery_soc` for battery state of charge and enter the usable battery
capacity in kWh.

New energy sensors begin collecting statistics after installation, so dashboard data
may take an hour or more to appear. See
[ENERGY_DASHBOARD_SETUP.md](ENERGY_DASHBOARD_SETUP.md) for additional guidance.

## Upgrading

The original nine sensor unique IDs are retained, so existing dashboards,
automations, and statistics should continue working. If Home Assistant already has an
unrelated entity with one of the new names, it may add a numeric suffix to that entity
ID.

After updating:

1. Restart Home Assistant.
2. Open the Sol-Ark integration and verify the plant and equipment devices.
3. Add the supplied energy entities to the Energy Dashboard.

## Troubleshooting

If setup fails:

1. Confirm the same credentials work at [Sol-Ark Cloud](https://www.solarkcloud.com).
2. Verify the plant ID from the portal URL.
3. Leave automatic API discovery enabled.
4. Check **Settings → System → Logs** for `custom_components.solark`.

If sensors become unavailable:

1. Confirm the Sol-Ark portal and data logger are online.
2. Open the integration entry and complete any reauthentication prompt.
3. Restart Home Assistant after upgrading the integration.
4. Download diagnostics from the integration menu when requesting support.

Diagnostics contain integration and equipment-health information but omit credentials,
tokens, serial numbers, and account identifiers.

## Support

Report problems through [GitHub Issues](https://github.com/babgvant/HomeAssistant_SolArk/issues).
Include the integration version, affected equipment model, Home Assistant logs, and
downloaded diagnostics. Never attach credentials or an unredacted HAR file.

## Development

Contributor notes and API behavior are documented in [context.md](context.md). The
detailed sanitized endpoint inventory is in
[docs/API_RESEARCH.md](docs/API_RESEARCH.md).
