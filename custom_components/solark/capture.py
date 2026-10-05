"""Bounded in-memory evidence for candidate power events, disabled by default."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone

POWER_KEYS = ("pv_power", "battery_power", "load_power", "grid_power")


class PowerCapture:
    """Store allowlisted evidence without extra requests or raw payloads."""

    def __init__(self, options):
        self.enabled = bool(options.get("diagnostic_capture", False))
        self.threshold = max(5, min(100, int(options.get("diagnostic_drop_percent", 25)))) / 100
        self.minimum = max(0, min(100000, int(options.get("diagnostic_min_watts", 500))))
        self.before = max(1, min(120, int(options.get("diagnostic_pre_samples", 10))))
        self.after = max(1, min(120, int(options.get("diagnostic_post_samples", 10))))
        self.limit = max(1, min(50, int(options.get("diagnostic_event_limit", 20))))
        self.ring = deque(maxlen=self.before)
        self.events = deque(maxlen=self.limit)
        self.pending = None
        self.remaining = 0
        self.total_events = 0

    def record(self, data, timings):
        if not self.enabled:
            return
        debug = data.get("debug_diagnostics", {})
        aggregation = data.get("aggregation", {}).get("pv_power", {})
        sample = {
            "utc": datetime.now(timezone.utc).isoformat(),
            "powers": {k: data.get("plant", {}).get("values", {}).get(k) for k in POWER_KEYS},
            "aggregation": {k: aggregation.get(k) for k in ("aggregation_method", "expected_inverters")},
            "contributing_count": len(aggregation.get("contributing_inverters", [])),
            "endpoint_errors": dict(data.get("endpoint_errors", {})),
            "endpoint_timing": deepcopy(timings),
            "endpoint_measurements": deepcopy(debug),
            "plant_flow_powers": {key: debug.get("plant", {}).get("plant_flow", {}).get(field)
                                  for key, field in (("pv_power", "raw_pv_power"),
                                                     ("battery_power", "battery_power"))},
        }
        # Source timestamps are evidence, never unrestricted cloud strings.
        for inverter in sample["endpoint_measurements"].get("inverters", {}).values():
            for endpoint in inverter.values():
                self._sanitize_timestamp(endpoint)
        for endpoint in sample["endpoint_measurements"].get("plant", {}).values():
            self._sanitize_timestamp(endpoint)
        reasons = []
        if sample["endpoint_errors"]: reasons.append("endpoint_failure")
        if sample["contributing_count"] < (aggregation.get("expected_inverters") or 0):
            reasons.append("incomplete_inverter_total")
        if self.ring:
            previous = self.ring[-1]
            if (previous["aggregation"] != sample["aggregation"]
                    or previous["contributing_count"] != sample["contributing_count"]):
                reasons.append("source_or_topology_change")
            for key in POWER_KEYS:
                old, new = previous["powers"].get(key), sample["powers"].get(key)
                if old is not None and new is not None and abs(old) >= self.minimum:
                    if abs(old) - abs(new) >= max(self.minimum, abs(old) * self.threshold):
                        reasons.append(f"candidate_dip:{key}")
            for key, new in sample["plant_flow_powers"].items():
                old = previous["plant_flow_powers"].get(key)
                if old is not None and new is not None and abs(old) >= self.minimum:
                    if abs(old) - abs(new) >= max(self.minimum, abs(old) * self.threshold):
                        reasons.append(f"candidate_plant_flow_dip:{key}")
        if self.pending is not None:
            self.pending["samples"].append(sample)
            if reasons:
                self.pending["triggers"].append({"utc": sample["utc"], "reasons": reasons})
            self.remaining -= 1
            if self.remaining <= 0:
                self.pending["complete"] = True
                self.pending = None
        elif reasons:
            self.total_events += 1
            event = {"complete": False, "triggers": [{"utc": sample["utc"], "reasons": reasons}],
                     "samples": list(self.ring) + [sample]}
            self.events.append(event)
            self.pending = event
            self.remaining = self.after
        self.ring.append(sample)

    @staticmethod
    def _sanitize_timestamp(endpoint):
        if "source_update_at" in endpoint:
            try:
                endpoint["source_update_at"] = datetime.fromisoformat(
                    str(endpoint["source_update_at"]).replace("Z", "+00:00")
                ).isoformat()
            except ValueError:
                endpoint["source_update_at"] = None

    def export(self):
        return deepcopy({"enabled": self.enabled, "storage": "memory_until_reload",
                         "total_events": self.total_events, "retained_events": len(self.events),
                         "limits": {"pre_samples": self.before, "post_samples": self.after,
                                    "events": self.limit, "drop_percent": self.threshold * 100,
                                    "minimum_watts": self.minimum},
                         "rolling_samples": list(self.ring), "events": list(self.events)})
