# Sol-Ark Cloud architecture and HAR research

This document records the investigation performed against integration version 5.0.2
and a sanitized browser capture from 2026-09-10. The raw HAR is deliberately not
stored in this repository. Identifiers, credentials, account details, addresses, and
personal data have been omitted.

## Existing architecture

Current data path:

```text
Sol-Ark OAuth/legacy login
  -> SolArkCloudAPI.get_plant_data()
     -> first inverter from /plant/{plant_id}/inverters
     -> /dy/store/{first_inverter_sn}/read
     -> /plant/energy/{plant_id}/flow
     -> /plant/{plant_id}/realtime
  -> SolArkCloudAPI.parse_plant_data()
  -> one flat coordinator.data dictionary
  -> nine fixed sensor entities on one generic device
```

The config flow asks for a username, password, and plant ID, discovers the current
API host from the portal JavaScript, and tests the same plant fetch used at runtime.
The entry polls every 30 seconds by default. A single `DataUpdateCoordinator` marks
the entire update failed when the required first-inverter request fails; the two
plant-level auxiliary calls are swallowed and replaced by empty dictionaries.

Architectural limitations:

- Only the first inverter is inspected. List position is used implicitly as identity.
- Plant, gateway, inverter, and battery concepts are not represented in normalized data.
- All entities use the config-entry ID as the device identifier and unique-ID prefix.
- Metadata and live measurements are mixed in a single poll path.
- Debug logging includes unsanitized raw inverter payloads and serial numbers.
- A token expiry causes login, but HTTP 401 does not clear/retry the token and there is
  no config-entry reauthentication flow.
- Missing values are coerced to zero, which makes offline/malformed data look real.
- `energy_today` is incorrectly marked `TOTAL_INCREASING` despite its daily reset.
- There are no tests, fixtures, lint configuration, or type-check configuration.
- Diagnostics exist but return the complete coordinator payload and do not redact
  serial numbers, plant/account IDs, email-like values, or other topology identifiers.
- Documentation claims Energy Dashboard compatibility while still requiring users to
  create Riemann-sum and template helpers manually.

## Authentication and request conventions

All useful API calls in the capture use `https://p2.api.solarkcloud.com`. The portal
origin/referer is `https://www.solarkcloud.com`. Authenticated requests use an
`Authorization` bearer header. OAuth uses JSON requests to `POST /oauth/token` with
either password-grant fields (`username`, `password`, `grant_type`, `client_id`) or
refresh-grant fields (`refresh_token`, `grant_type`). The successful envelope is:

```json
{"code": 0, "msg": "...", "data": {"access_token": "<redacted>", "refresh_token": "<redacted>", "expires_in": 0}, "success": true}
```

All observed application responses use `{code, msg, data, success}` envelopes and
ISO-8601 UTC timestamps or date strings. Request identifiers occur in path segments
and query parameters. The integration must never log their values at normal levels.

## Useful API inventory

| Method and path | Important request fields | Scope and useful response fields |
|---|---|---|
| `GET /api/v1/plants` | `page`, `limit`, `status`, `type`, sorting | Plant discovery and summary metadata |
| `GET /api/v1/plant/{plant_id}` | `id`, `lan` | Plant name/status/type/timezone and nested realtime PV totals; contains sensitive owner/contact/location data that must be discarded |
| `GET /api/v1/plant/{plant_id}/realtime` | `id` | Plant `pac`, `etoday`, `emonth`, `eyear`, `etotal`, `efficiency`, `updateAt`, rated total power |
| `GET /api/v1/plant/energy/{plant_id}/flow` | `date` | Aggregate instantaneous PV, battery, grid, load, generator and microinverter power; SOC and direction/existence flags |
| `GET /api/v1/plant/energy/{plant_id}/day` | `date`, `id`, `lan` | Historical intraday PV, battery, SOC, grid, and load series |
| `GET /api/v1/plant/energy/{plant_id}/generation/use` | none | A small energy-use summary: `load`, `pv`, `batteryCharge`, `gridSell`; the capture does not establish its time period |
| `GET /api/v1/plant/{plant_id}/inverters` | pagination, `stationId`, `status`, `type`, `sn` | Stable inverter `id`/`sn`, gateway serial link, status, model, firmware, rated/current power, PV today/total, update time |
| `GET /api/v1/inverter/{inverter_id}` | `sn` | Detailed inverter metadata, operating status, model/protocol, firmware and PV energy totals; response also contains sensitive user data that must be discarded |
| `GET /api/v1/inverter/{inverter_id}/flow` | none | Per-inverter instantaneous power flow and MPPT power list |
| `GET /api/v1/inverter/battery/{inverter_id}/realtime` | `sn`, `lan` | Battery power/SOC/voltage/current/temperature/limits/status and native today/month/year/lifetime charge/discharge energy |
| `GET /api/v1/inverter/params` | `sn`, `devType`, `lan` | Parameter catalogue with numeric field IDs, labels, and units |
| `GET /api/v1/inverter/{inverter_id}/day` | `sn`, `date`, `edate`, comma-separated `params`, `lan` | Requested inverter parameter series. Latest record supplies current electrical values and native cumulative energy counters |
| `GET /api/v1/gateways` | pagination, `plantId`, filters | Stable gateway ID/serial, online state, signal, firmware/hardware, model, last communication, upload interval, plant relationship |
| `GET /api/v1/batteries` | pagination, `plantId`, inverter/gateway/serial filters | Individually registered batteries; the captured installation returned none |
| `GET /api/v1/plant/{plant_id}/events` | date range, type/code, pagination | Plant alarms/warnings/faults with time, inverter serial, code, description and source |
| `GET /api/v1/plant/{plant_id}/eventCount` | none | Current warning/fault counts and update time |
| `GET /api/v1/dy/store/{inverter_sn}/read` | `sn` | Large live/configuration register snapshot; useful as compatibility fallback, but it also contains settings and placeholder MPPT ramps |

Observed health-count routes (`/inverters/count`, `/gateways/count`,
`/batteries/count`, `/plant/{id}/inverterCount`) add no data not available from the
primary lists. They should not be part of the normal polling path.

### Parameter catalogue relevant to sensors

The following IDs are API catalogue IDs, not customer identifiers:

- Battery: SOC 16, temperature 17, voltage 18, current 19, power 20,
  BMS SOC 73, voltage 98, current 101, temperature 104, charge/discharge limits
  102/103, today charge/discharge 81/82, lifetime charge/discharge 79/80.
- Load: total power 21, phase power 85/86, daily/lifetime consumption 83/84,
  load voltage 598/599.
- Grid: power 23, frequency 24, phase current 25/26/27, phase voltage 44/45/46,
  daily import/export 91/92, lifetime import/export 93/94.
- Inverter: temperature 28, output power 29, PV power 467, output frequency 60,
  output voltage 67/68/465, output current 70/71/466, DC/AC temperatures 75/76,
  microinverter power 78, generator power 77, generator today/total 209/210,
  generator voltage/frequency 596/597.
- PV strings/MPPT: current 30/31/603, voltage 34/35/604, power 600/601/602,
  PV today/total 96/97.
- Alternate generator family: voltage 607, power 608, today/total energy 609/610,
  frequency 611.

## Evidence about parallel systems

The sanitized capture has three inverters and two gateways. At the same timestamp:

- Inverter PV powers sum exactly to plant PV power.
- Inverter battery magnitudes sum exactly to plant battery magnitude.
- Inverter grid powers sum exactly to plant grid power.
- Inverter load powers sum exactly to plant load power.
- Inverter PV-today values sum exactly to plant PV-today.
- Inverter PV-lifetime values do **not** sum to the plant PV-lifetime value.

Therefore plant flow and plant realtime are authoritative for aggregate entities.
Individual flow endpoints are authoritative only for their inverter entities. The
integration must not construct plant power by summing inverter power. The mismatch in
lifetime PV also proves that summing arbitrary per-inverter lifetime counters would be
unsafe, possibly because of device replacement, counter epochs, or cloud aggregation.

## Proposed Home Assistant device hierarchy

```text
Plant device (identifier: API plant ID)
  Gateway devices (identifier: gateway serial, via_device: plant)
    Inverter devices (identifier: inverter serial, via_device: linked gateway)
      Battery device only when the batteries API supplies an individual stable serial
```

If a gateway relation is absent, the inverter is linked directly to the plant. Battery
telemetry exposed only as an inverter-wide aggregate belongs to the inverter device;
it must not create a fictional individually addressable battery.

Existing nine entity unique IDs remain `{config_entry_id}_{key}` on the plant device.
New scoped unique IDs use `{config_entry_id}:{scope}:{stable_id}:{key}`. Entity/device
registry migration should move the old generic device to the plant identifier without
changing those nine entity unique IDs.

## Proposed normalized coordinator model

```text
SolArkData
  fetched_at / feature flags / endpoint errors
  plant
    stable id, name, status, metadata
    realtime power, native PV counters, availability timestamps
  gateways[stable serial]
    metadata, state, plant relationship
  inverters[stable serial]
    metadata, gateway relationship, state
    flow, electrical measurements, native energy counters
    aggregate battery telemetry and native battery counters
  batteries[stable serial]
    metadata, inverter/gateway relationship, telemetry when individually addressable
```

Each endpoint contributes independently. A failed auxiliary inverter endpoint leaves
only that feature unavailable; it does not invalidate plant flow or unrelated devices.
Static topology/metadata is cached and refreshed much less often than power flow.

## Proposed entity set

Plant entities:

- Existing PV, battery, grid, load, grid-import, grid-export power, battery SOC,
  PV energy today, and PV lifetime energy entities.
- Battery charge/discharge power, generator power, Smart Load/microinverter power.
- Native PV month/year/lifetime counters and last-update/status/event-count sensors.
- Energy Dashboard counters for PV, grid import/export, battery charge/discharge, and
  load. Use native plant counters when discovered; otherwise use persistent integration
  of authoritative plant aggregate power, never a RAM-only accumulator.

Gateway entities:

- Online state, signal/communications quality, last communication, upload interval,
  and connected inverter count. Model, serial, firmware, and hardware are device info.

Inverter entities:

- PV total and MPPT powers; load/grid/battery/generator/microinverter powers; split
  nonnegative battery charge/discharge and grid import/export powers.
- Native PV, load, grid import/export, generator, and battery charge/discharge daily
  and lifetime energy counters.
- Grid/output/load phase voltage, phase current, frequency, PV voltage/current/power,
  inverter/DC/AC temperatures, SOC, status, run state, and last update.

Battery entities:

- For an inverter aggregate: SOC, voltage, current, power, temperature, charge and
  discharge current limits, status, and native charge/discharge energy.
- For individually registered batteries: the same subset when the batteries endpoint
  supplies measurements and a stable serial. No individual battery was present in the
  capture, so this path must be tolerant and fixture-driven.

## Native energy counters and fallbacks

Native and preferred:

- Plant PV today/month/year/lifetime (`etoday`, `emonth`, `eyear`, `etotal`).
- Per-inverter PV today/lifetime (96/97 and inverter summary).
- Per-inverter load today/lifetime (83/84).
- Per-inverter grid import/export today (91/92) and lifetime (93/94).
- Per-inverter battery charge/discharge today and lifetime (81/82, 79/80, also
  explicit fields in the battery realtime endpoint).
- Per-inverter generator today/lifetime (209/210 or 609/610).

Still requiring plant-level integration in the observed API:

- Aggregate grid import and export energy.
- Aggregate battery charge and discharge energy.
- Aggregate load energy.
- Aggregate generator energy if multiple inverters are present.

Those aggregate fallbacks must integrate the already authoritative plant flow streams,
restore their last total/sample after restart, ignore unavailable intervals, and avoid
bridging long API outages. They are not derived by summing unproven inverter counters.

Daily reset counters use `SensorStateClass.TOTAL`; lifetime counters use
`TOTAL_INCREASING`. Power-to-energy fallbacks use `TOTAL_INCREASING` and kWh.

## Ambiguities and risks

- `/generation/use` names useful energy fields but the capture does not prove whether
  they are daily, selected-period, or lifetime values; it is not used as a lifetime
  source until that is established.
- Flow battery magnitude requires direction flags. Battery realtime uses the opposite
  signed convention in this capture. Normalization must expose positive discharge and
  negative charge consistently.
- Inverter status integer meanings and event type/code meanings are not described by
  the API; raw values should be preserved alongside conservative online/offline logic.
- Some BMS fields use sentinel values (`-100`) or zeros when no BMS is connected.
- `dy/store` exposes a known fixed MPPT placeholder ramp and many writable settings;
  it is a fallback, not the primary measurement endpoint.
- The captured `model` string may be generic. Device metadata should prefer a detailed
  non-empty model but tolerate firmware-specific omissions.
- The API has no public compatibility contract. Missing endpoints and fields must only
  disable affected entities.

## Incremental implementation plan

1. Add this sanitized research record, HAR inventory tooling, normalized models, and
   endpoint parsing tests.
2. Add topology discovery, cached metadata, partial endpoint failure handling, and
   device-registry hierarchy while preserving legacy entity unique IDs.
3. Add declarative plant and per-inverter operational sensors.
4. Add gateway sensors and metadata.
5. Add aggregate and individually addressable battery sensors.
6. Add native cumulative energy sensors and correct daily counter state classes.
7. Add persistent plant energy fallbacks for counters not proven native.
8. Harden diagnostics, redaction, authentication retry/reauth, and logging.
9. Expand tests for discovery, hierarchy, parsing, metadata, outages, and recovery.
10. Rewrite installation, Energy Dashboard, parallel-system, diagnostics, and
    troubleshooting documentation.

