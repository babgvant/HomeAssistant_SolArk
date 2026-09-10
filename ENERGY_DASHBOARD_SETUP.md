# Home Assistant Energy Dashboard setup

Sol-Ark Cloud 5.1.0 and newer supplies every entity needed by Home Assistant's Energy
Dashboard. Do not create Riemann-sum helpers or battery template sensors.

## Configure the dashboard

Open **Settings → Dashboards → Energy** and select:

| Energy Dashboard field | Sol-Ark entity |
|---|---|
| Solar production | `sensor.solark_energy_total` |
| Energy consumed from the grid | `sensor.solark_grid_import_energy` |
| Energy returned to the grid | `sensor.solark_grid_export_energy` |
| Battery energy going in | `sensor.solark_battery_charge_energy` |
| Battery energy coming out | `sensor.solark_battery_discharge_energy` |

Save the configuration and allow Home Assistant time to create long-term statistics.
New energy entities normally need an hour or more before useful dashboard graphs appear.

## How the totals work

Solar production uses Sol-Ark's native cumulative plant counter. Grid import/export,
battery charge/discharge, and load use persistent integration of the authoritative
plant power-flow values because the observed cloud API does not provide proven
plant-wide lifetime counters for them.

Fallback totals:

- are stored/restored by Home Assistant across restart and integration reload;
- ignore unavailable samples and do not bridge prolonged API outages;
- use separate nonnegative import/export and charge/discharge power streams;
- start at zero when the entity is first created and cannot reconstruct earlier usage.

## Parallel systems

Always choose the plant entities listed above. Per-inverter energy sensors are
diagnostic information only. The integration never sums inverter counters into a plant
total because counters can have different epochs after service or replacement.

## Troubleshooting

If an entity is absent, restart Home Assistant after updating the integration. If it is
unavailable, confirm `sensor.solark_grid_import_power` and the corresponding source
power entity have values, then inspect the integration diagnostics and logs.

If the Energy Dashboard does not list an entity, wait for at least two successful
updates and verify its unit is `kWh`, device class is `energy`, and state class is
`total_increasing` in **Developer tools → States**.

Do not delete existing Energy Dashboard statistics unless you intentionally want to
lose their history.
