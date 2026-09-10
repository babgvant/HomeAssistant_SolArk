# Development context

This file contains implementation context that is useful to maintainers but is not
needed for normal installation or operation.

## Data authority

Plant-level flow and realtime responses are authoritative for operational and Energy
Dashboard entities. Gateway and inverter readings are informational only. Do not sum
inverter measurements to produce plant totals.

The analyzed parallel installation demonstrated that instantaneous inverter powers
could match the plant aggregate while lifetime inverter counters did not necessarily
match the plant lifetime counter. Equipment replacement, reset epochs, and cloud-side
aggregation can all make such sums unsafe.

## Energy behavior

The cloud response provides a native plant PV lifetime counter. The analyzed capture
did not establish equivalent plant-wide lifetime counters for grid import/export,
battery charge/discharge, or load.

Those plant entities integrate the corresponding plant power streams and restore their
state through Home Assistant. They skip unavailable data and do not bridge unusually
long update gaps. They cannot reconstruct energy from before the entities were added
or during a prolonged cloud outage.

Daily reset counters use `SensorStateClass.TOTAL`; lifetime and persistent integrated
counters use `SensorStateClass.TOTAL_INCREASING`.

## Polling model

- Plant flow is refreshed at the configured polling interval.
- Plant realtime energy information is refreshed with the plant poll.
- Topology and metadata are cached for 30 minutes.
- Informational inverter flow, battery, and parameter details are cached for five
  minutes.
- Failure of an optional equipment endpoint should affect only that data group.
- Authentication rejection initiates Home Assistant reauthentication.

## Identity and compatibility

Plant IDs, gateway serials, inverter serials, and battery serials form device registry
identities. Inverters use their gateway as `via_device` when the relation exists.

The original nine entities retain their `{config_entry_id}_{key}` unique IDs. New
scoped equipment entities use `{config_entry_id}:{scope}:{stable_id}:{key}`.

## Endpoint-specific conventions

- Plant/inverter flow battery power is an unsigned magnitude interpreted with `toBat`
  and `batTo` direction flags.
- Battery realtime power is already signed: positive discharge, negative charge.
- Grid power is normalized as positive import and negative export.
- `minPower` represents Smart Load or AC-coupled/microinverter contribution where the
  accompanying presence flags apply.
- Missing and malformed measurements remain `None`; they must not be coerced to zero.
- BMS temperature `-100` is treated as a missing-value sentinel.
- The legacy `dy/store` response may contain placeholder MPPT ramps and should remain a
  compatibility fallback rather than the primary sensor source.

## Security

Never commit raw HAR captures or production API responses. They can contain usernames,
passwords, bearer/refresh tokens, cookies, email addresses, locations, serial numbers,
and account identifiers.

Request logging must include only redacted route shapes and parameter names. Diagnostics
must report counts, feature availability, detected models, update health, and normalized
key names without exposing topology identifiers or raw payloads.

Use `tools/har_inventory.py` to inspect future captures structurally. Review its output
before copying any material into fixtures or documentation.

## References

- [Sanitized API and architecture research](docs/API_RESEARCH.md)
- [Energy Dashboard behavior](ENERGY_DASHBOARD_SETUP.md)
- [Normalization tests](tests/test_models.py)
