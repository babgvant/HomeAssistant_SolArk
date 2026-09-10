# Sol-Ark Cloud for Home Assistant

A Home Assistant custom integration for Sol-Ark Cloud plants, including native plant
power, Energy Dashboard-ready energy sensors, parallel inverter discovery, gateways,
and battery/BMS diagnostics.

## Highlights

- Plant-level PV, load, grid, battery, generator, and Smart Load power
- Separate nonnegative grid import/export and battery charge/discharge power
- Persistent kWh entities for the Home Assistant Energy Dashboard
- Plant, gateway, inverter, and aggregate battery devices with stable API identities
- Parallel inverter support without double-counting plant totals
- Native inverter energy counters and electrical/BMS detail as diagnostic information
- Automatic API-host discovery, token retry, reauthentication, and partial-failure handling
- Secret-safe diagnostics

Plant endpoints are authoritative for all operational and Energy Dashboard metrics.
Gateway and inverter metrics are informational only and are never summed to manufacture
plant totals.

## Installation

### HACS

1. In HACS, open **Integrations** and choose **Custom repositories**.
2. Add `https://github.com/HammondAutomationHub/HomeAssistant_SolArk` as an Integration.
3. Install **SolArk Cloud** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and select **SolArk Cloud**.

### Manual

Copy `custom_components/solark` into the `custom_components` directory in your Home
Assistant configuration, restart Home Assistant, and add **SolArk Cloud** from the UI.

## Configuration

Enter the credentials used at `www.solarkcloud.com` and the numeric plant ID shown in
the portal URL. API auto-discovery should normally remain enabled. The default poll
interval is 30 seconds; inverter detail and topology are internally cached at slower
rates to avoid unnecessary cloud calls.

Credentials are stored in the Home Assistant config entry. If Sol-Ark rejects them,
Home Assistant starts a reauthentication flow instead of requiring the integration to
be removed and re-added.

## Device hierarchy

The integration creates devices that follow the cloud topology:

```text
Sol-Ark Plant
  Gateway / data logger
    Inverter
      Aggregate battery telemetry (when exposed)
```

An inverter without a gateway link is attached directly to the plant. An individual
battery device is created only when the API provides a stable battery serial; an
inverter-wide BMS aggregate is not presented as a fictional physical battery.

Device identifiers use stable plant IDs, gateway serials, and inverter serials. Model,
firmware, hardware, and serial metadata are populated when Sol-Ark supplies them.

## Plant sensors

The principal plant entities are:

| Entity | Unit | Meaning |
|---|---:|---|
| `sensor.solark_pv_power` | W | Authoritative total PV power, including AC-coupled PV when reported |
| `sensor.solark_battery_power` | W | Positive discharge, negative charge |
| `sensor.solark_battery_charge_power` | W | Nonnegative charge stream |
| `sensor.solark_battery_discharge_power` | W | Nonnegative discharge stream |
| `sensor.solark_battery_soc` | % | Plant aggregate battery state of charge |
| `sensor.solark_grid_power` | W | Positive import, negative export |
| `sensor.solark_grid_import_power` | W | Nonnegative import stream |
| `sensor.solark_grid_export_power` | W | Nonnegative export stream |
| `sensor.solark_load_power` | W | Authoritative plant load |
| `sensor.solark_generator_power` | W | Generator power when supported |
| `sensor.solark_smart_load_power` | W | Smart Load / microinverter power when supported |
| `sensor.solark_energy_today` | kWh | Native PV energy for the current day |
| `sensor.solark_energy_total` | kWh | Native lifetime plant PV energy |
| `sensor.solark_grid_import_energy` | kWh | Persistent plant grid-import energy |
| `sensor.solark_grid_export_energy` | kWh | Persistent plant grid-export energy |
| `sensor.solark_battery_charge_energy` | kWh | Persistent plant battery-charge energy |
| `sensor.solark_battery_discharge_energy` | kWh | Persistent plant battery-discharge energy |
| `sensor.solark_load_energy` | kWh | Persistent plant load energy |

The original nine entity unique IDs are retained. Existing entity registry entries,
dashboards, automations, and statistics therefore continue to work. Home Assistant may
append a suffix if a new entity ID is already occupied by another integration.

## Informational equipment sensors

Gateway devices expose connection status, signal, last communication, and attached
inverter count. Inverter devices expose available PV/load/grid/battery/generator power,
native device energy counters, grid electrical data, temperature, state, and update
time. Aggregate inverter battery devices expose available SOC, voltage, current,
temperature, power, and native charge/discharge totals.

These equipment-level entities are marked diagnostic. They are useful for balancing,
fault isolation, and checking communications, but should not be used as plant totals.
Fields unsupported by a particular model remain unavailable rather than reporting a
misleading zero.

## Energy Dashboard

No Riemann-sum or template helpers are required.

In **Settings → Dashboards → Energy**, configure:

- Solar production: `sensor.solark_energy_total`
- Grid consumption: `sensor.solark_grid_import_energy`
- Return to grid: `sensor.solark_grid_export_energy`
- Battery energy in: `sensor.solark_battery_charge_energy`
- Battery energy out: `sensor.solark_battery_discharge_energy`

The PV total is a native Sol-Ark plant counter. The captured API did not expose proven
native plant-wide lifetime counters for grid, battery, or load. Those entities therefore
integrate the authoritative plant flow streams, restore their totals after Home
Assistant restart/reload, and avoid bridging long API outages. They start at zero when
first created; Home Assistant records their long-term statistics from that point.

Do not select the diagnostic per-inverter energy entities in the Energy Dashboard.
Their counters are device-level and may have different epochs after replacement or
service. In the supplied parallel-system capture, inverter lifetime PV totals did not
equal the cloud's authoritative plant lifetime total.

## Parallel inverter behavior

The integration discovers every inverter and its gateway relation. Each inverter gets
its own diagnostic entities, but plant entities always come from plant `/flow` and
`/realtime` endpoints. This prevents double counting and remains correct when an
inverter is replaced, temporarily offline, or associated with a different gateway.

The integration does not calculate aggregate SOC by averaging inverter SOC values; it
uses the plant value supplied by Sol-Ark.

## Diagnostics and troubleshooting

Download diagnostics from **Settings → Devices & services → SolArk Cloud → three-dot
menu → Download diagnostics**. Diagnostics contain counts, detected models, supported
features, endpoint health, update state, and available normalized keys. They omit
credentials, tokens, cookies, email addresses, serials, and account/plant identifiers.

If entities are unavailable:

1. Confirm the Sol-Ark portal is reachable and the inverter/data logger is online.
2. Open the integration entry for any reauthentication prompt.
3. Check Home Assistant logs for `custom_components.solark`.
4. Download diagnostics and inspect `endpoint_errors`; an auxiliary endpoint failure
   affects only its related detail entities.
5. Increase the polling interval if the cloud reports rate limiting.

API auto-discovery reads the current API base from the portal frontend. If discovery
fails, the last-known API URL is retained and can be overridden in integration options.

## Known API limitations

- Sol-Ark Cloud is undocumented and can vary by model, firmware, account region, and
  portal deployment.
- The API exposes integer status/event codes without a public mapping. The integration
  preserves conservative status information rather than guessing labels.
- Some devices return zero or sentinel BMS fields when no BMS is connected.
- Individual physical batteries are not always registered separately; many systems
  expose only an inverter-associated aggregate.
- Persistent fallback energy cannot reconstruct energy consumed before the entity was
  created or during a prolonged cloud outage.

The sanitized endpoint research and field catalogue are documented in
[`docs/API_RESEARCH.md`](docs/API_RESEARCH.md).

## Development

Run the dependency-free normalization tests with:

```bash
python -m unittest discover -s tests -v
```

The raw HAR is intentionally excluded. `tools/har_inventory.py` emits only normalized
routes, field shapes, and selected non-secret measurements for future captures.

## Support

Report issues at <https://github.com/HammondAutomationHub/HomeAssistant_SolArk/issues>.
Include sanitized Home Assistant diagnostics, integration version, inverter model, and
firmware version. Never attach an unredacted HAR or credentials.
