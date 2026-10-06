# Power dip investigation — October 5, 2026

## October 6 capture and 5.1.2 correction

The supplied 5.1.1 event export contains 223 unique retained polls, with capture
enabled. Eleven polls exhibit a staggered-upload subtotal: plant flow PV and
plant realtime power equal only one or two newly updated inverter summary powers,
while the other contributors retain timestamps from the previous five-minute
upload. The following poll restores complete coverage. For example, at 12:06:56
America/Chicago, plant PV is 3,726 W with summary powers 3,726, 5,195, and 5,874 W;
only the first inverter has the new upload timestamp. At 12:07:27 the total is
14,823 W and all three upload timestamps are aligned again. Battery, load, and
grid also change in these partial snapshots. A balanced subtotal at 12:06:56
passes the old PV-only sanity check; later imbalanced subtotals hold PV alone.
The capture supports a cloud aggregation/upload transition, not a physical dip.
It does not establish the cloud service's internal cause.

Version 5.1.2 compares like-for-like plant and inverter-summary `pac` values and
checks timestamp grouping. It applies the guard only when flow PV matches plant
realtime power and auxiliary flow is inactive. It does not substitute AC summary
power for PV or reconstruct battery/grid/load by scaling. A matching partial
upload rejects all site flow power, holding the last balanced complete upload
for up to two minutes; with no baseline or an expired baseline values become
unavailable. Complete inverter PV sums remain usable. Unverifiable coverage does
not trigger rejection. Raw flow balance and coverage evidence remain available
in diagnostics. All eleven captured subtotal polls are detected in offline replay.

Deploy the complete `custom_components/solark` directory and restart Home Assistant.
Verify diagnostics report version 5.1.2. This change prevents future rejected
subtotals from being recorded; existing History dips remain. Production behavior
still needs verification after installation.

The sections below describe the earlier investigation and deployment state.

## Evidence and limits

The clean checkout was dd80221, version 5.1.0. No connection to running Home
Assistant was available: installed version, current entity IDs and October 3 raw
responses remain unverified. The original CSV was not supplied. Synthetic fallback
reproduction proves a code path, not the cause of recorded dips.

The HAR spans 22.911 seconds, October 5 around 17:10 UTC. It contains one plant
flow/realtime pair, two three-device inverter lists (all status 1), and three
individual flows fetched 15–19 seconds after the plant snapshot. Relevant requests
returned HTTP 200; flow latency was 227–634 ms.

| Measurement | Plant | Individual inverter sum |
| --- | ---: | ---: |
| PV | 15,034 W | 3,764 + 5,281 + 5,989 = 15,034 W |
| Battery charge magnitude | 12,801 W | 2,825 + 4,638 + 5,338 = 12,801 W |
| Load | 2,640 W | 900 + 870 + 870 = 2,640 W |
| Grid import | 170 W | 40 + 80 + 50 = 170 W |

Battery `toBat=true`, `batTo=false` means negative normalized power (charging);
grid `gridTo=true`, `toGrid=false` means positive import. `minPower=0` is a real
zero. No device is missing here. Battery realtime supplies no selected power
fields. Inverter day queries request voltage parameters, not PV/battery power.
Plant realtime `updateAt=17:07:06Z` is roughly three minutes older than HTTP fetch;
successful requests need not contain fresh telemetry. Plant flow has no source
timestamp here.
The captured flow/realtime responses declare `no-cache`, `no-store`,
`must-revalidate`, and `max-age=0`. This argues against ordinary HTTP response
caching; it does not rule out stale data inside the cloud service.

The portal's `/api/v1/plant/energy/{id}/day` chart responses contain five series,
146 records each, at 00:00, 00:05, …, 12:05 local chart time. Per-inverter day
records are five minutes apart with device offsets (:01:52, :01:57, :02:03).
This differs from 30-second Home Assistant polling and can miss a 31-second
excursion. The HAR does not prove averaging, interpolation or live UI polling
cadence: it has only one plant-flow request. Duplicate chart requests came during
navigation, not a sustained polling observation.

Five-minute cached detail failures do not explain one-poll recovery every 899
seconds: missing detail ordinarily persists until the next detail refresh. A short
inverter list affects fresh summary counters while cached flow power is separately
sourced. Battery uses plant flow independently, so PV fallback cannot explain its
dips. A cloud update transition remains a candidate; none was captured. The
recurring root cause remains unconfirmed.

## Correction and capture

Version 5.1.1 removes `plant_flow_fallback` for an incomplete inverter sum. Existing
code warns plant PV may omit a slave; the README promises no partial site totals.
Incomplete PV now becomes unavailable with `incomplete_inverter_sum`; zero remains
valid. This corrects an unsafe source switch without claiming to fix the observed
cadence. No smoothing or stale replacement readings were added. Battery/grid/load
continue using plant flow. Inverter PV still refreshes every five minutes; failed
optional details await the scheduled refresh. Missing detail sample age is now
null. Day source times are retained; naive cloud times stay naive because their
timezone is not declared.

Capture is disabled by default. Triggers are a magnitude decrease of at least 25%
and 500 W in PV, battery, load or grid; incomplete PV totals; source/topology/count
changes; or endpoint failure. Charging uses absolute battery power. Candidates are
evidence, not automatically rejected measurements.
Raw plant-flow PV/battery decreases trigger too, even when normalized PV is cached.

Defaults retain 10 preceding and 10 following polls per event, up to 20 events,
plus a 10-sample rolling buffer. At 30 seconds, this is about five minutes on each
side. Options configure thresholds (5–100%, 0–100,000 W), preceding/following
samples (1–120 each), and events (1–50); runtime clamps these limits too. Persistent
triggers cannot extend one event forever. Old events are evicted when full;
`total_events` versus `retained_events` shows eviction. Exports can include an
in-progress event with `complete=false`.

Downloaded diagnostics include `power_capture`: UTC event/sample times, normalized
power, method/counts, positional inverter labels, endpoint error classes, call start
times/latency, raw numeric measurement comparisons, direction flags, cache ages,
and available source times. Capture uses existing polls, adds no requests, and
writes no disk or log files. It excludes HAR bodies, credentials, cookies, tokens,
serials and device/account IDs. It clears on reload/restart/options change.

## Deployment and unattended validation

1. Copy the entire checkout's `custom_components/solark` into Home Assistant's
   configuration `custom_components/solark`, then restart Home Assistant. This
   patch has not been deployed automatically.
2. Download diagnostics and verify `integration_version=5.1.1`. Open the plant and
   inverter devices under Settings → Devices & services → SolArk Cloud and copy
   their actual entity IDs. Use those in History/Developer Tools; obsolete
   unavailable entity names do not establish physical inverter outages.
3. Open **Configure**, enable **bounded power diagnostic capture**, keep 30-second
   polling and the default limits, and leave it running during daylight for two
   hours. No manual dip watching is necessary.
4. Download integration diagnostics afterward, before any reload/restart. Disable
   capture through Configure when finished; export first because options reload.
5. Check event UTC spacing for the ~899-second pattern. If the buffer fills early,
   shorten the collection interval or adjust thresholds/limits.

Interpretation:

- Battery dip present in raw plant-flow magnitude: the cloud supplied that value.
  Compare direction flags, normalized sign, realtime source time and balance.
- Stable plant flow with changed PV contributors/source: inspect inverter flow/day
  availability, cache ages and source timestamps. Incomplete PV must be unavailable.
- Fixed inverter PV for minutes while plant flow varies: five-minute detail cadence,
  not a contemporaneous sum. Missing source times prevent proving simultaneity.
- Compare verified entity History CSVs with portal five-minute chart timestamps.
  Absence of a short excursion from that chart does not prove a false raw sample.

Acceptance: known topology survives short lists; incomplete PV never switches to
lower plant fallback; genuine zero stays numeric; battery dips retain independent
plant evidence; event windows capture recovery without observation. Resolving cloud
versus physical excursions may still require independent inverter telemetry.

Reproduce structural HAR analysis locally with `tools/power_har_report.py`.
Never commit the HAR; no raw capture or production payload fixtures were added.

## Validation performed

28 focused tests passed: real API client tests, normalization, stubbed coordinator,
capture bounds/before-after windows, raw dips while selected PV is cached, genuine
zeros, mandatory failures, source timestamps and export privacy. Python compilation
and `git diff --check` passed. The API tests bypass package setup so no HA server
is needed. The full HA sensor-metadata suite could not collect in this Windows
Python 3.12 test environment (missing HA runtime dependencies, most recently
`jinja2`). This is not a live HA integration test or production validation.
