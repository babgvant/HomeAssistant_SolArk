# Home Assistant Energy Dashboard setup

Sol-Ark Cloud 5.1.0 and newer supplies every entity needed by Home Assistant's Energy
Dashboard. Do not create Riemann-sum helpers or battery template sensors.

## Configure the dashboard

Open **Settings → Dashboards → Energy** and select:

| Energy Dashboard section | Field | Sol-Ark entity |
|---|---|---|
| Solar panels | Solar production energy | `sensor.solark_energy_total` |
| Solar panels | Solar production power | `sensor.solark_pv_power` |
| Electricity grid | Energy consumed from the grid | `sensor.solark_grid_import_energy` |
| Electricity grid | Energy returned to the grid | `sensor.solark_grid_export_energy` |
| Home battery storage | Energy going in to the battery | `sensor.solark_battery_charge_energy` |
| Home battery storage | Energy coming out of the battery | `sensor.solark_battery_discharge_energy` |

The entity picker shows the entity's display name and device. Select the entries on
the Sol-Ark plant device—for example, **Energy Total** and **PV Power** under
**P-House** in the screenshot. The display name is optional and can be left unchanged.

For **Type of power measurement** under **Home battery storage**, select **Two
Sensors**, then choose:

- **Power charging the battery:** `sensor.solark_battery_charge_power`
- **Power discharging the battery:** `sensor.solark_battery_discharge_power`

Select `sensor.solark_battery_soc` for **Battery state of charge sensor** and enter
the usable battery capacity in kWh. Display names are only labels; correct any
charge/discharge label copied from a previous selection so it describes the selected
entity.

Save the configuration and allow Home Assistant time to create long-term statistics.
New energy entities normally need an hour or more before useful dashboard graphs appear.

## Parallel systems

Choose the plant entities listed above for whole-site Energy Dashboard totals. Use
per-inverter energy sensors only when you want to monitor an individual inverter.

For parallel systems, plant PV power and energy are completeness-checked sums of the
discovered inverter PV values. Inspect `contributing_inverters`,
`expected_inverters`, and `aggregation_method` when a value is unavailable. Load,
grid, and battery power retain the site-wide Sol-Ark plant-flow values. Their
`energy_balance` attribute can reveal disagreement between reported sources and sinks.

## Troubleshooting

If an entity is absent, restart Home Assistant after updating the integration. If it is
unavailable, confirm `sensor.solark_grid_import_power` and the corresponding source
power entity have values, then inspect the integration diagnostics and logs.

If the Energy Dashboard does not list an entity, wait for at least two successful
updates and verify its unit is `kWh`, device class is `energy`, and state class is
`total_increasing` in **Developer tools → States**.

Do not delete existing Energy Dashboard statistics unless you intentionally want to
lose their history.
