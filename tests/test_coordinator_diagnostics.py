"""Regression checks for endpoint provenance and inverter summary freshness."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1] / "custom_components" / "solark"


def load_coordinator():
    """Load the coordinator with minimal HA stubs for a standalone test run."""
    ha = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})
    config_entries.ConfigEntryAuthFailed = type("ConfigEntryAuthFailed", (Exception,), {})
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    helpers = types.ModuleType("homeassistant.helpers")
    update = types.ModuleType("homeassistant.helpers.update_coordinator")
    update.DataUpdateCoordinator = type(
        "DataUpdateCoordinator", (),
        {"__class_getitem__": classmethod(lambda cls, item: cls),
         "__init__": lambda self, *args, **kwargs: None},
    )
    update.UpdateFailed = type("UpdateFailed", (Exception,), {})
    custom = types.ModuleType("custom_components")
    custom.__path__ = [str(ROOT.parent)]
    solark = types.ModuleType("custom_components.solark")
    solark.__path__ = [str(ROOT)]
    api = types.ModuleType("custom_components.solark.api")
    api.SolArkCloudAPI = type("SolArkCloudAPI", (), {})
    api.SolArkCloudAPIError = type("SolArkCloudAPIError", (Exception,), {})
    api.SolArkCloudAuthenticationError = type(
        "SolArkCloudAuthenticationError", (api.SolArkCloudAPIError,), {}
    )
    const = types.ModuleType("custom_components.solark.const")
    const.CONF_PLANT_ID = "plant_id"
    const.CONF_SCAN_INTERVAL = "scan_interval"
    const.DEFAULT_SCAN_INTERVAL = 30
    modules = {
        "homeassistant": ha,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.update_coordinator": update,
        "custom_components": custom,
        "custom_components.solark": solark,
        "custom_components.solark.api": api,
        "custom_components.solark.const": const,
    }
    with patch.dict(sys.modules, modules):
        model_spec = importlib.util.spec_from_file_location(
            "custom_components.solark.models", ROOT / "models.py"
        )
        models = importlib.util.module_from_spec(model_spec)
        with patch.dict(sys.modules, {"custom_components.solark.models": models}):
            model_spec.loader.exec_module(models)
            spec = importlib.util.spec_from_file_location(
                "custom_components.solark.coordinator", ROOT / "coordinator.py"
            )
            coordinator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(coordinator)
    return coordinator


class FakeAPI:
    summaries = [
        {"sn": "one", "id": 1, "etoday": 5.0, "etotal": 50.0, "pac": 100},
        {"sn": "two", "id": 2, "etoday": 6.0, "etotal": 60.0, "pac": 200},
    ]

    async def async_get_plant_metadata(self): return {}
    async def async_get_gateways(self): return []
    async def async_get_batteries(self): return []
    async def async_get_inverters(self): return list(self.summaries)
    async def async_get_plant_flow(self):
        return {"pvPower": 300, "gridOrMeterPower": 0, "gridTo": True,
                "battPower": 0, "batTo": True, "loadOrEpsPower": 300}
    async def async_get_plant_realtime(self): return {"etoday": 11.0, "etotal": 110.0}
    async def async_get_plant_generation_use(self): return {"pv": 11.0}
    async def async_get_inverter_flow(self, inverter_id): return {}
    async def async_get_inverter_battery(self, inverter_id, serial): return {}
    async def async_get_inverter_measurements(self, inverter_id, serial, ids): return {}


class CoordinatorDiagnosticsTests(unittest.TestCase):
    def incident(self):
        """Sanitized October 20 arithmetic; optional inverter endpoints are empty."""
        module = load_coordinator()
        api = FakeAPI()
        timestamp = datetime.now(timezone.utc).isoformat()
        api.summaries = [dict(sn=str(i), id=i, pac=power, updateAt=timestamp)
                         for i, power in enumerate((2934, 4189, 4776), 1)]
        snapshot = dict(pvPower=11899, loadOrEpsPower=11860,
                        gridOrMeterPower=1020, toGrid=True, battPower=66, toBat=True)
        realtime = dict(pac=11899, updateAt=timestamp)
        async def flow(): return dict(snapshot)
        async def rt(): return dict(realtime)
        api.async_get_plant_flow, api.async_get_plant_realtime = flow, rt
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={"diagnostic_capture": True}, title="Site")
        return module, api, snapshot, realtime, module.SolArkDataUpdateCoordinator(None, entry, api)

    def test_complete_coverage_balance_mismatch_and_recovery(self):
        module, api, snapshot, realtime, coordinator = self.incident()
        started = datetime.now(timezone.utc)
        for _ in range(2):
            # The same upload remains fresh beyond the old two-minute PV hold.
            with patch.object(module, "datetime") as clock:
                clock.now.return_value = started + timedelta(seconds=_ * 180)
                result = asyncio.run(coordinator._async_update_data())
            self.assertEqual(result["plant"]["values"]["pv_power"], 11899)
            attributes = result["aggregation"]["pv_power"]
            self.assertEqual(attributes["aggregation_method"], "coverage_corroborated_plant_flow")
            self.assertEqual(attributes["quality"], "power_balance_mismatch")
            self.assertEqual(attributes["site_flow_coverage"]["status"], "complete")
            sanity = attributes["plant_flow_sanity"]
            self.assertFalse(sanity["accepted"])
            self.assertEqual(sanity["power_balance_error"], -1047)
            self.assertAlmostEqual(sanity["tolerance_watts"], 647.3)
            self.assertTrue(all(inv["values"]["pv_power"] is None for inv in result["inverters"].values()))
            self.assertIsNone(coordinator._last_valid_plant_pv)
            self.assertIsNone(coordinator._last_complete_site_flow)
        # No two-minute outage: each fresh corroborated poll uses current plant PV.
        exported = coordinator.power_capture.export()["rolling_samples"][-1]
        self.assertEqual(exported["powers"]["pv_power"], 11899)
        self.assertEqual(exported["aggregation"]["quality"], "power_balance_mismatch")
        self.assertEqual(exported["aggregation"]["plant_flow_sanity"]["reason"], "power_balance_mismatch")
        self.assertEqual(exported["endpoint_measurements"]["power_balance"]["power_balance_error"], -1047)
        snapshot.update(pvPower=11726, loadOrEpsPower=2070, gridOrMeterPower=7110, battPower=2475)
        recovered = asyncio.run(coordinator._async_update_data())
        self.assertEqual(recovered["plant"]["values"]["pv_power"], 11726)
        self.assertEqual(recovered["energy_balance"]["power_balance_error"], 71)
        self.assertEqual(recovered["aggregation"]["pv_power"]["aggregation_method"], "validated_plant_flow")
        self.assertEqual(recovered["aggregation"]["pv_power"]["quality"], "balanced")

    def test_corroboration_cannot_bypass_other_guards(self):
        for case in ("short_list", "missing_list", "stale", "future", "unaligned", "missing_time",
                     "different_ac", "invalid_pv", "invalid_load", "generator", "smart_load", "known_pv"):
            with self.subTest(case=case):
                module, api, snapshot, realtime, coordinator = self.incident()
                if case in ("short_list", "missing_list"):
                    # Discover topology before the response loses a contributor.
                    asyncio.run(coordinator._async_update_data())
                    if case == "short_list":
                        api.summaries = api.summaries[:2]
                    else:
                        async def missing(): return None
                        api.async_get_inverters = missing
                elif case in ("stale", "future"):
                    offset = -361 if case == "stale" else 120
                    timestamp = (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()
                    realtime["updateAt"] = timestamp
                    for item in api.summaries: item["updateAt"] = timestamp
                elif case == "unaligned":
                    realtime["updateAt"] = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
                elif case == "missing_time": realtime.pop("updateAt")
                elif case == "different_ac": realtime["pac"] = 10000
                elif case == "invalid_pv": snapshot["pvPower"] = float("nan")
                elif case == "invalid_load": snapshot["loadOrEpsPower"] = -1
                elif case == "generator": snapshot["genOn"] = True
                elif case == "smart_load": snapshot["minPower"] = 100
                elif case == "known_pv":
                    async def inv_flow(inverter_id): return {"pvPower": 15000} if inverter_id == 1 else {}
                    api.async_get_inverter_flow = inv_flow
                result = asyncio.run(coordinator._async_update_data())
                self.assertIsNone(result["plant"]["values"]["pv_power"])
                self.assertNotEqual(result["aggregation"]["pv_power"]["aggregation_method"], "coverage_corroborated_plant_flow")

    def test_lost_corroboration_uses_only_bounded_balanced_hold(self):
        module, api, snapshot, realtime, coordinator = self.incident()
        snapshot.update(pvPower=7123, loadOrEpsPower=6037)
        asyncio.run(coordinator._async_update_data())
        accepted_at = coordinator._last_valid_plant_pv[1]
        snapshot.update(pvPower=11899, loadOrEpsPower=11860)
        corroborated = asyncio.run(coordinator._async_update_data())
        self.assertEqual(corroborated["plant"]["values"]["pv_power"], 11899)
        self.assertEqual(coordinator._last_valid_plant_pv, (7123, accepted_at))
        realtime.pop("updateAt")
        held = asyncio.run(coordinator._async_update_data())
        self.assertEqual(held["plant"]["values"]["pv_power"], 7123)
        self.assertEqual(held["aggregation"]["pv_power"]["quality"], "held")
        coordinator._last_valid_plant_pv = (7123, accepted_at - timedelta(seconds=121))
        for invalid in (None, -1, float("inf"), float("nan")):
            snapshot["pvPower"] = invalid
            expired = asyncio.run(coordinator._async_update_data())
            self.assertIsNone(expired["plant"]["values"]["pv_power"])
        snapshot["pvPower"] = 11899
        self.assertIsNone(asyncio.run(coordinator._async_update_data())["plant"]["values"]["pv_power"])

    def test_partial_power_is_unavailable_and_zero_is_valid(self):
        module = load_coordinator()
        api = FakeAPI()
        powers = {1: 13105, 2: 253}
        async def flow(inverter_id):
            value = powers[inverter_id]
            return {} if value is None else {"pvPower": value}
        api.async_get_inverter_flow = flow
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={"diagnostic_capture": True}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        first = asyncio.run(coordinator._async_update_data())
        self.assertEqual(first["plant"]["values"]["pv_power"], 13358)
        powers[2] = None
        coordinator._inverter_details_at = None
        second = asyncio.run(coordinator._async_update_data())
        self.assertIsNone(second["plant"]["values"]["pv_power"])
        self.assertEqual(second["plant"]["values"]["battery_power"], 0)
        self.assertIsNone(second["debug_diagnostics"]["inverters"]["inverter_2"]["flow"]["sample_age_seconds"])
        powers[2] = 0
        coordinator._inverter_details_at = None
        third = asyncio.run(coordinator._async_update_data())
        self.assertEqual(third["plant"]["values"]["pv_power"], 13105)
        exported = coordinator.power_capture.export()
        self.assertIn("incomplete_inverter_total", exported["events"][0]["triggers"][0]["reasons"])
        self.assertNotIn('"one"', __import__('json').dumps(exported))
        self.assertIn("latency_ms", exported["rolling_samples"][-1]["endpoint_timing"]["plant_flow"])

    def test_flow_failure_keeps_energy_but_clears_site_power_and_recovers(self):
        module = load_coordinator()
        api = FakeAPI()
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={"diagnostic_capture": True}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        first = asyncio.run(coordinator._async_update_data())
        self.assertEqual(first["plant"]["values"]["pv_power"], 300)
        good_flow = api.async_get_plant_flow
        async def fail(): raise module.SolArkCloudAPIError("secret response")
        api.async_get_plant_flow = fail
        result = asyncio.run(coordinator._async_update_data())
        self.assertEqual(result["plant"]["values"]["energy_today"], 11)
        self.assertEqual(result["plant"]["values"]["energy_total"], 110)
        for key in module.SITE_POWER_KEYS:
            self.assertIsNone(result["plant"]["values"].get(key), key)
        self.assertIsNone(result["plant"]["values"]["battery_soc"])
        self.assertIsNone(result["energy_balance"])
        self.assertEqual(result["aggregation"]["grid_power"]["aggregation_method"], "unavailable_site_flow")
        self.assertEqual(result["endpoint_errors"]["plant_flow"], "SolArkCloudAPIError")
        exported = coordinator.power_capture.export()
        self.assertEqual(exported["total_events"], 1)
        self.assertNotIn("secret", str(exported))
        api.async_get_plant_flow = good_flow
        recovered = asyncio.run(coordinator._async_update_data())
        self.assertEqual(recovered["plant"]["values"]["pv_power"], 300)
        self.assertEqual(recovered["plant"]["values"]["load_power"], 300)
        self.assertNotIn("plant_flow", recovered["endpoint_errors"])

    def test_flow_failure_preserves_complete_inverter_pv(self):
        module = load_coordinator()
        api = FakeAPI()
        async def fail(): raise module.SolArkCloudAPIError("unavailable")
        async def inverter_flow(inverter_id): return {"pvPower": inverter_id * 100}
        api.async_get_plant_flow = fail
        api.async_get_inverter_flow = inverter_flow
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={"diagnostic_capture": True}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        result = asyncio.run(coordinator._async_update_data())
        self.assertEqual(result["plant"]["values"]["pv_power"], 300)
        self.assertEqual(result["aggregation"]["pv_power"]["aggregation_method"], "sum_per_inverter")
        self.assertIsNone(result["plant"]["values"]["load_power"])

    def test_total_outage_does_not_publish_cached_telemetry(self):
        for raises in (True, False):
            with self.subTest(raises=raises):
                module = load_coordinator()
                api = FakeAPI()
                entry = types.SimpleNamespace(data={"plant_id": "site"}, options={"diagnostic_capture": True}, title="Site")
                coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
                asyncio.run(coordinator._async_update_data())

                async def unavailable():
                    if raises:
                        raise module.SolArkCloudAPIError("secret response")
                    return {}

                for name in ("async_get_inverters", "async_get_plant_flow",
                             "async_get_plant_realtime", "async_get_plant_generation_use"):
                    setattr(api, name, unavailable)
                with self.assertRaises(module.UpdateFailed):
                    asyncio.run(coordinator._async_update_data())
                exported = coordinator.power_capture.export()
                self.assertNotIn("secret", str(exported))

    def test_auth_rejection_still_requests_reauthentication(self):
        module = load_coordinator()
        api = FakeAPI()
        async def rejected(): raise module.SolArkCloudAuthenticationError("rejected")
        api.async_get_plant_flow = rejected
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        with self.assertRaises(module.ConfigEntryAuthFailed):
            asyncio.run(coordinator._async_update_data())

    def test_realtime_failure_keeps_complete_inverter_energy_and_flow(self):
        module = load_coordinator()
        api = FakeAPI()
        async def fail(): raise module.SolArkCloudAPIError("unavailable")
        api.async_get_plant_realtime = fail
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        result = asyncio.run(coordinator._async_update_data())
        self.assertEqual(result["plant"]["values"]["energy_total"], 110)
        self.assertEqual(result["plant"]["values"]["load_power"], 300)

    def test_empty_inverter_flows_use_balanced_plant_power_but_not_energy(self):
        module = load_coordinator()
        api = FakeAPI()
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        first = asyncio.run(coordinator._async_update_data())

        self.assertEqual(first["aggregation"]["pv_power"]["aggregation_method"], "validated_plant_flow")
        self.assertEqual(first["plant"]["values"]["pv_power"], 300)
        self.assertEqual(first["energy_balance"]["power_balance_error"], 0)
        self.assertIsNone(first["debug_diagnostics"]["inverters"]["inverter_1"]["day_parameters"]["pv_energy_today"])
        self.assertEqual(first["debug_diagnostics"]["inverters"]["inverter_1"]["flow"]["status"], "empty_or_unavailable")

        # A short current list keeps topology but must not publish an old
        # inverter value as today's complete production.
        api.summaries = [dict(FakeAPI.summaries[0], etoday=7.0)]
        second = asyncio.run(coordinator._async_update_data())
        self.assertEqual(len(second["inverters"]), 2)
        self.assertIsNone(second["plant"]["values"]["energy_today"])
        self.assertIsNone(second["debug_diagnostics"]["pv_comparison"]["plant_minus_inverter_today"])
        self.assertEqual(second["debug_diagnostics"]["inverters"]["inverter_2"]["summary"]["status"], "stale_cached")

    def test_bad_plant_dip_is_held_then_expires_and_recovers(self):
        module = load_coordinator()
        api = FakeAPI()
        snapshot = {"pvPower": 15184, "gridOrMeterPower": 200, "gridTo": True,
                    "battPower": 10244, "toBat": True, "loadOrEpsPower": 5310}
        async def flow(): return dict(snapshot)
        api.async_get_plant_flow = flow
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        first = asyncio.run(coordinator._async_update_data())
        self.assertEqual(first["plant"]["values"]["pv_power"], 15184)
        self.assertEqual(first["aggregation"]["pv_power"]["plant_flow_sanity"]["power_balance_error"], -170)
        accepted_at = coordinator._last_valid_plant_pv[1]
        snapshot["pvPower"] = 4000
        rejected = asyncio.run(coordinator._async_update_data())
        self.assertEqual(rejected["plant"]["values"]["pv_power"], 15184)
        self.assertEqual(rejected["aggregation"]["pv_power"]["aggregation_method"], "held_validated_plant_flow")
        self.assertGreaterEqual(rejected["aggregation"]["pv_power"]["sample_age_seconds"], 0)
        self.assertEqual(coordinator._last_valid_plant_pv[1], accepted_at)
        coordinator._last_valid_plant_pv = (15184, accepted_at - timedelta(seconds=121))
        expired = asyncio.run(coordinator._async_update_data())
        self.assertIsNone(expired["plant"]["values"]["pv_power"])
        # A real production drop is accepted when consumption/charging also falls.
        snapshot.update(pvPower=4000, gridOrMeterPower=0, battPower=0, loadOrEpsPower=4000)
        recovered = asyncio.run(coordinator._async_update_data())
        self.assertEqual(recovered["plant"]["values"]["pv_power"], 4000)
        self.assertEqual(recovered["aggregation"]["pv_power"]["aggregation_method"], "validated_plant_flow")
        snapshot.update(pvPower=0, loadOrEpsPower=0)
        night = asyncio.run(coordinator._async_update_data())
        self.assertEqual(night["plant"]["values"]["pv_power"], 0)

    def test_invalid_initial_plant_power_is_unavailable(self):
        module = load_coordinator()
        api = FakeAPI()
        async def flow():
            return {"pvPower": 0, "gridOrMeterPower": 0, "battPower": 0,
                    "loadOrEpsPower": 10000}
        api.async_get_plant_flow = flow
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        result = asyncio.run(coordinator._async_update_data())
        self.assertIsNone(result["plant"]["values"]["pv_power"])
        self.assertEqual(result["aggregation"]["pv_power"]["plant_flow_sanity"]["reason"], "power_balance_mismatch")

    def test_partial_upload_holds_all_site_power_then_expires_and_recovers(self):
        module = load_coordinator()
        api = FakeAPI()
        api.summaries = [{"sn": str(i), "id": i, "pac": power, "updateAt": timestamp}
                         for i, power, timestamp in (
                             (1, 3726, "2026-10-06T17:01:54Z"),
                             (2, 5195, "2026-10-06T17:02:00Z"),
                             (3, 5874, "2026-10-06T17:02:07Z"))]
        snapshot = {"pvPower": 14795, "battPower": 12800, "toBat": True,
                    "gridOrMeterPower": 170, "gridTo": True, "loadOrEpsPower": 2165}
        realtime = {"pac": 14795, "updateAt": "2026-10-06T17:02:07Z"}
        async def flow(): return dict(snapshot)
        async def rt(): return dict(realtime)
        api.async_get_plant_flow, api.async_get_plant_realtime = flow, rt
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={"diagnostic_capture": True}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        full = asyncio.run(coordinator._async_update_data())
        accepted_at = coordinator._last_complete_site_flow[1]
        # Sanitized arithmetic from the captured one-inverter upload: balanced
        # enough to pass the old PV-only guard, yet two contributors are absent.
        api.summaries[0]["updateAt"] = "2026-10-06T17:06:54Z"
        realtime.update(pac=3726, updateAt="2026-10-06T17:06:54Z")
        snapshot.update(pvPower=3726, battPower=141, loadOrEpsPower=950,
                        gridOrMeterPower=2190, gridTo=False, toGrid=True)
        held = asyncio.run(coordinator._async_update_data())
        for key in module.SITE_POWER_KEYS:
            self.assertEqual(held["plant"]["values"][key], full["plant"]["values"][key])
            self.assertEqual(held["aggregation"][key]["aggregation_method"], "held_complete_site_flow")
        self.assertEqual(coordinator._last_complete_site_flow[1], accepted_at)
        self.assertEqual(held["energy_balance"]["pv_power"], 3726)
        self.assertEqual(held["energy_balance"]["battery_charge_power"], 141)
        exported = coordinator.power_capture.export()
        self.assertEqual(exported["rolling_samples"][-1]["plant_flow_powers"]["pv_power"], 3726)
        self.assertEqual(exported["rolling_samples"][-1]["endpoint_measurements"]["site_flow_coverage"]["status"], "partial")
        coordinator._last_complete_site_flow = (coordinator._last_complete_site_flow[0], accepted_at - timedelta(seconds=121))
        expired = asyncio.run(coordinator._async_update_data())
        for key in module.SITE_POWER_KEYS:
            self.assertIsNone(expired["plant"]["values"][key])
        # Initial partial upload also cannot manufacture a complete value.
        initial = asyncio.run(module.SolArkDataUpdateCoordinator(None, entry, api)._async_update_data())
        self.assertIsNone(initial["plant"]["values"]["pv_power"])
        for summary in api.summaries:
            summary.update(pac=0, updateAt="2026-10-06T17:07:07Z")
        realtime.update(pac=0, updateAt="2026-10-06T17:07:07Z")
        snapshot.update(pvPower=0, battPower=0, loadOrEpsPower=0, gridOrMeterPower=0)
        recovered = asyncio.run(coordinator._async_update_data())
        self.assertEqual(recovered["plant"]["values"]["pv_power"], 0)
        self.assertEqual(recovered["plant"]["values"]["battery_power"], 0)
        self.assertEqual(recovered["aggregation"]["pv_power"]["aggregation_method"], "validated_plant_flow")

    def test_complete_inverter_pv_survives_partial_plant_upload(self):
        module = load_coordinator()
        api = FakeAPI()
        api.summaries = [
            {"sn": "one", "id": 1, "pac": 4000, "updateAt": "2026-10-06T17:06:54Z"},
            {"sn": "two", "id": 2, "pac": 6000, "updateAt": "2026-10-06T17:02:07Z"},
        ]
        async def flow():
            return {"pvPower": 4000, "battPower": 3000, "toBat": True,
                    "gridOrMeterPower": 0, "loadOrEpsPower": 1000}
        async def rt(): return {"pac": 4000, "updateAt": "2026-10-06T17:06:54Z"}
        async def inverter_flow(inverter_id): return {"pvPower": {1: 4000, 2: 6000}[inverter_id]}
        api.async_get_plant_flow, api.async_get_plant_realtime = flow, rt
        api.async_get_inverter_flow = inverter_flow
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={}, title="Site")
        result = asyncio.run(module.SolArkDataUpdateCoordinator(None, entry, api)._async_update_data())
        self.assertEqual(result["plant"]["values"]["pv_power"], 10000)
        self.assertEqual(result["aggregation"]["pv_power"]["aggregation_method"], "sum_per_inverter")
        self.assertIsNone(result["plant"]["values"]["battery_power"])


if __name__ == "__main__":
    unittest.main()
