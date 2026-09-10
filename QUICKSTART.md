# Sol-Ark Cloud quick start

1. Install the repository as a HACS custom integration and restart Home Assistant.
2. Find the plant ID in the Sol-Ark portal URL after opening the plant overview.
3. Add **SolArk Cloud** under **Settings → Devices & services**.
4. Enter the portal username, password, and plant ID. Keep API auto-discovery enabled.
5. After the first update, open the Sol-Ark plant device and verify PV, load, grid,
   battery, and SOC values.

For the Energy Dashboard, select the integration's plant entities directly:

- Solar: `sensor.solark_energy_total`
- Solar production power: `sensor.solark_pv_power`
- Grid consumption: `sensor.solark_grid_import_energy`
- Grid return: `sensor.solark_grid_export_energy`
- Battery in: `sensor.solark_battery_charge_energy`
- Battery out: `sensor.solark_battery_discharge_energy`

No helpers or YAML template sensors are required. See
[`ENERGY_DASHBOARD_SETUP.md`](ENERGY_DASHBOARD_SETUP.md) for details.

Parallel installations also show gateway, inverter, and aggregate battery diagnostic
devices. Use the plant entities for dashboards and automations that represent the whole
site. Use equipment entities to monitor or troubleshoot an individual device.

If setup fails, verify the same credentials at `www.solarkcloud.com`. If an existing
entry later rejects credentials, complete the Home Assistant reauthentication prompt.
Diagnostics are available from the integration entry and intentionally omit secrets
and equipment identifiers.
