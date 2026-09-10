"""Tests for secret-free Sol-Ark normalization."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "solark" / "models.py"
_SPEC = importlib.util.spec_from_file_location("solark_models", _PATH)
models = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(models)


class FlowTests(unittest.TestCase):
    def test_grid_import_and_battery_charge_split(self) -> None:
        values = models.flow_values({"pvPower": 4000, "minPower": 50, "existsMin": True, "battPower": 1200, "toBat": True, "gridOrMeterPower": 300, "gridTo": True, "loadOrEpsPower": 3150})
        self.assertEqual(values["pv_power"], 4050)
        self.assertEqual(values["battery_power"], -1200)
        self.assertEqual(values["battery_charge_power"], 1200)
        self.assertEqual(values["battery_discharge_power"], 0)
        self.assertEqual(values["grid_import_power"], 300)
        self.assertEqual(values["grid_export_power"], 0)

    def test_grid_export_and_battery_discharge_split(self) -> None:
        values = models.flow_values({"battPower": 900, "batTo": True, "gridOrMeterPower": 250, "toGrid": True})
        self.assertEqual(values["battery_power"], 900)
        self.assertEqual(values["grid_power"], -250)
        self.assertEqual(values["grid_import_power"], 0)
        self.assertEqual(values["grid_export_power"], 250)

    def test_missing_fields_stay_unavailable(self) -> None:
        values = models.flow_values({})
        self.assertIsNone(values["pv_power"])
        self.assertIsNone(values["battery_soc"])

    def test_mppt_values_are_individual_only(self) -> None:
        values = models.flow_values({"pvPower": 30, "pv": [{"power": 10}, {"power": 20}]})
        self.assertEqual(values["pv_power"], 30)
        self.assertEqual(values["pv_power_1"], 10)
        self.assertEqual(values["pv_power_2"], 20)


class BatteryTests(unittest.TestCase):
    def test_realtime_sign_is_converted(self) -> None:
        values = models.battery_values({"power": -2251, "bmsSoc": 85, "bmsVolt": 53.72, "etotalChg": "236.1", "etotalDischg": "70.8"})
        self.assertEqual(values["battery_power"], -2251)
        self.assertEqual(values["battery_charge_power"], 2251)
        self.assertEqual(values["battery_charge_energy"], 236.1)

    def test_bms_temperature_sentinel_is_missing(self) -> None:
        self.assertIsNone(models.battery_values({"bmsTemp": -100})["battery_temperature"])


class ParameterTests(unittest.TestCase):
    def test_latest_parameter_record(self) -> None:
        data = {"infos": [{"id": 93, "records": [{"value": "10.1"}, {"value": None}, {"value": "10.4"}]}, {"id": 94, "records": {"list": [{"value": "2.3"}]}}]}
        self.assertEqual(models.latest_parameter_values(data), {93: "10.4", 94: "2.3"})

    def test_malformed_parameter_payload(self) -> None:
        self.assertEqual(models.latest_parameter_values({"infos": None}), {})


if __name__ == "__main__":
    unittest.main()
