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
- Plant-level TOU targets, start times, grid-charge permissions, start SOC,
  and current controls for energy-cost automations

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
Energy totals require every expected inverter to contribute. PV power can fall back
to plant flow when all six PV/grid/battery/load balance inputs are finite,
nonnegative, and agree within the larger of 500 W or 5% of total flow. It also
rejects plant PV below known inverter production beyond that tolerance. Active
generator or nonzero Smart Load/AC-coupled modes cannot use this fallback.
Rejected plant samples retain the last accepted plant PV for at most two minutes,
then become unavailable. A complete inverter sum remains preferred. These entities expose
`contributing_inverters`, `expected_inverters`, and `aggregation_method` attributes.
PV power also exposes `plant_flow_sanity` and fallback `sample_age_seconds`.
This check catches inconsistent snapshots, but cannot detect a consistently partial
cloud snapshot. PV power in watts can legitimately decrease; only accumulated
energy in kWh is expected to rise during a day before its daily reset.

Plant flow, realtime energy, and inverter summaries poll every 30 seconds by
default (configurable in integration options). Inverter detail telemetry refreshes
every five minutes; gateway/plant metadata refreshes every 30 minutes. Cloud source
readings may be older than the polling time.

Day-based API queries use the Home Assistant timezone. If plant flow fails,
independent inverter and energy readings remain available while affected site
power and SOC readings become unavailable. A complete cloud telemetry outage
makes the integration's telemetry entities unavailable.

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

## Time-of-use controls

The integration automatically identifies the master by **Modbus SN** (`modbusSn`)
in inverter settings: position **1** is the master, and positions **2+** are
secondary inverters. No manual serial selection is needed. Device names and API
list order do not affect master detection.

The **plant device** exposes these configuration controls. The integration routes
their reads and writes through the automatically detected master inverter:

| Control | Purpose |
|---|---|
| TOU 1–6 battery SOC | Battery target for each period (0–100%) |
| TOU 1–6 start time | Period start in the inverter's local clock |
| Time of use | Enable the TOU schedule |
| TOU 1–6 grid charging | Allow grid charging in each period |
| Grid charging | Battery-settings permission to charge from the grid |
| Grid charge start SOC | SOC threshold that triggers grid charging (0–100%) |
| Grid charge current | DC battery charge limit in integer amps, up to the current battery charge limit |

Times have minute precision. Controls are
unavailable when the account or inverter cannot return a complete settings form.
Settings refresh every minute, independently of telemetry.

Each edit reads the current settings and submits the corresponding captured portal
form: work-mode for TOU edits, battery settings for grid-charge permission, start
SOC, and current. Other fields in that form are preserved, including generator
settings, battery limits, voltage targets, and active weekdays. Battery controls
are unavailable if the full battery form is missing; TOU controls remain usable.
Existing master controls move to the plant on reload while retaining their entity
IDs and user customizations. Plant control identities remain stable if the detected
master changes. Writes target only the detected master. Secondary inverters
inherit the master's settings; the integration never sends TOU writes to them.
If settings cannot be read for every discovered inverter, or no unique position-1
master is found, TOU writes are disabled until detection succeeds. The master
position is checked again immediately before each write. Secondary TOU controls
from the initial implementation are removed on reload after master detection.

A successful command means the cloud accepted the update for delivery. Submitted
values are shown for up to two minutes while waiting for cloud readback; if they
are not confirmed, controls revert to the values returned by the cloud. Avoid
simultaneous edits in the portal while automations are updating TOU settings.

### Using the controls for predictive charging

With TOU enabled, **both Grid charging and the active period's TOU grid charging
switch must be on**. These permissions do not force immediate charging. The
battery-settings start SOC triggers charging; the active period's battery SOC is
the charging target. For example, start SOC 40% and a TOU target of 80% permit
charging when SOC reaches 40%, toward 80%. SOC of 60% alone does not meet that
start condition. Keep the start threshold below the charging target. See the
[Sol-Ark programming guide, pages 11–12](https://www.sol-ark.com/wp-content/uploads/2024/08/Inverter-Programming-Guide-V2.0-3-2.pdf).

Home Assistant automations can combine tariff windows, solar forecasts, battery
SOC, and expected consumption to choose the six periods and their targets. Use
`number.set_value`, `time.set_value`, and `switch.turn_on`/`switch.turn_off` with
the actual entity IDs on the plant device. Configure the current limit, start
threshold, times, and targets first, then enable the intended charging period and
grid-charge permission. Disabling a period's charge permission does not disable
the TOU schedule or solar charging.

The integration provides the controls; it does not calculate forecasts or an
optimal schedule. Avoid rewriting unchanged values every telemetry poll. Allow
for one-minute settings polling and up to two minutes of pending cloud readback;
an accepted command is not proof of charging power. Check battery charging and
grid import telemetry to verify the result. Current is DC amps at the battery,
not grid AC amps or watts; parallel-system scaling depends on inverter behavior.

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

For recurring power dips, enable **bounded power diagnostic capture** in the
integration's **Configure** options, leave it running, then download diagnostics
before reloading or restarting. See [power-dip investigation](docs/POWER_DIP_INVESTIGATION.md)
for deployment, limits, interpretation and unattended validation.

## Support

Report problems through [GitHub Issues](https://github.com/babgvant/HomeAssistant_SolArk/issues).
Include the integration version, affected equipment model, Home Assistant logs, and
downloaded diagnostics. Never attach credentials or an unredacted HAR file.

## Development

Contributor notes and API behavior are documented in [context.md](context.md). The
detailed sanitized endpoint inventory is in
[docs/API_RESEARCH.md](docs/API_RESEARCH.md).
