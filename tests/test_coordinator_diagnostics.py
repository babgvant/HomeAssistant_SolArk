"""Regression checks for endpoint provenance and inverter summary freshness."""
from __future__ import annotations

import asyncio
from datetime import timedelta
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

    def test_required_endpoint_failure_is_captured(self):
        module = load_coordinator()
        api = FakeAPI()
        async def fail(): raise module.SolArkCloudAPIError("secret response")
        api.async_get_plant_flow = fail
        entry = types.SimpleNamespace(data={"plant_id": "site"}, options={"diagnostic_capture": True}, title="Site")
        coordinator = module.SolArkDataUpdateCoordinator(None, entry, api)
        with self.assertRaises(module.UpdateFailed):
            asyncio.run(coordinator._async_update_data())
        exported = coordinator.power_capture.export()
        self.assertEqual(exported["total_events"], 1)
        self.assertNotIn("secret", str(exported))

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


if __name__ == "__main__":
    unittest.main()
